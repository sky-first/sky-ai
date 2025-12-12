# api/routes/agents.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from api.schemas import QueryRequest, QueryResponse, QueryResultMeta
from agent_registry.loader import get_agent_config, AgentNotFoundError
from core.agents.generic_sql_agent import run_agent_once
from core.llm.providers import LangChainChatOpenAIProvider
from core.rag.embeddings import OpenAIEmbeddingProvider
from core.agents.context_retrieval import build_retrieval_context_for_question
from core.logging_utils import log_event
from db.session import get_db

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/{agent_id}/query", response_model=QueryResponse)
async def query_agent(
    agent_id: str,
    body: QueryRequest,
    db: Session = Depends(get_db),
) -> QueryResponse:
    try:
        agent_config = get_agent_config(agent_id)
    except AgentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # LLMs
    llm_orchestrator = LangChainChatOpenAIProvider(model="gpt-4o-mini", temperature=0.0)
    llm_specialist = LangChainChatOpenAIProvider(model="gpt-4o", temperature=0.0)
    llm_formatter = LangChainChatOpenAIProvider(model="gpt-4o", temperature=0.0)

    # 🔹 Provider de embeddings (RAG)
    embedding_provider = OpenAIEmbeddingProvider()

    retrieval_context: list[str] = []
    if body.space_id:
        retrieval_context = build_retrieval_context_for_question(
            db=db,
            embedding_provider=embedding_provider,
            space_id=body.space_id,
            crew_ids=body.crew_ids or [],
            question=body.question,
            top_k=10,
        )

    state = run_agent_once(
        question=body.question,
        agent_config=agent_config,
        llm_orchestrator=llm_orchestrator,
        llm_specialist=llm_specialist,
        llm_formatter=llm_formatter,
        user_id=body.user_id,
        space_id=body.space_id,
        crew_ids=body.crew_ids or [],
        thread_id=body.thread_id,
        retrieval_context=retrieval_context,  # 🔹 NOVO
    )

    answer = state.get("answer") or ""
    data = state.get("data") or []
    detected_language = state.get("detected_language")
    chosen_table = state.get("chosen_table")
    sql = state.get("sql")
    error = state.get("error")

    data_sample = data[:15] if isinstance(data, list) else []

    meta = QueryResultMeta(
        detected_language=detected_language,
        chosen_table=chosen_table,
        sql=sql,
        num_rows=len(data),
        error=error,
    )

    log_event(
        "api_query_agent",
        {
            "agent_id": agent_id,
            "user_id": body.user_id,
            "space_id": body.space_id,
            "crew_ids": body.crew_ids,
            "question": body.question[:200],
            "answer_preview": answer[:200],
            "num_rows": len(data),
            "error": error[:200] if error else None,
        },
    )

    return QueryResponse(
        answer=answer,
        data_sample=data_sample,
        meta=meta,
    )

#!/usr/bin/env python3
"""Testa uma pergunta específica para verificar se retorna dados"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from sqlalchemy import text
from db.base import SessionLocal, engine
from core.data_sources.factory import DataSourceFactory
from core.llm.providers import LangChainChatOpenAIProvider
from core.agents.generic_sql_agent import run_agent_once
from core.agents.context_retrieval import build_retrieval_context_for_question
from core.rag.embeddings import OpenAIEmbeddingProvider
from core.auth.models import UserContext, User
from uuid import UUID
from api.routes.connection_query import load_agent_config_from_connection

TEST_SPACE_ID = "e409079b-5bbf-4249-a769-2010609c30f2"
TEST_CONNECTION_ID = "1fd6fee8-bf03-4e82-9c85-419a228ef726"
TEST_USER_ID = "00000000-0000-0000-0000-000000000000"

question = "Quais são os principais motivos para os créditos emitidos?"

db = SessionLocal()
try:
    with engine.connect() as raw_conn:
        result = raw_conn.execute(
            text("SELECT id, name, connector_id AS type, config FROM data_connections WHERE id = :id"),
            {"id": TEST_CONNECTION_ID}
        ).first()
        
        import json as json_lib
        config_data = result[3] if isinstance(result[3], dict) else json_lib.loads(result[3]) if isinstance(result[3], str) else {}
        
        class TempDataConnection:
            def __init__(self, id, name, type, config):
                self.id = id
                self.name = name
                self.type = type
                self.config = config
        
        conn = TempDataConnection(
            id=str(result[0]),
            name=result[1],
            type=result[2] or "bigquery",
            config=config_data
        )
    
    datasource = DataSourceFactory.build_from_dataconnection(conn)
    agent_config = load_agent_config_from_connection(
        db=db,
        space_id=TEST_SPACE_ID,
        connection_id=TEST_CONNECTION_ID,
        crew_ids=None,
    )
    
    llm = LangChainChatOpenAIProvider(model="gpt-4o-mini", temperature=0.0)
    embedding_provider = OpenAIEmbeddingProvider(model="text-embedding-3-large")
    
    test_user = User(
        id=UUID(TEST_USER_ID),
        email="test@example.com",
        name="Test User",
        is_active=True
    )
    user_ctx = UserContext(
        user=test_user,
        space_id=UUID(TEST_SPACE_ID) if TEST_SPACE_ID else None,
        crew_id=None,
        permissions=[],
    )
    
    retrieval_context = []
    try:
        retrieval_context = build_retrieval_context_for_question(
            db=db,
            embedding_provider=embedding_provider,
            space_id=TEST_SPACE_ID,
            crew_ids=[],
            question=question,
            top_k=10,
        )
    except Exception:
        retrieval_context = []
    
    print(f"Testando: {question}")
    final_state = run_agent_once(
        question=question,
        user_ctx=user_ctx,
        agent_config=agent_config,
        data_source=datasource,
        db_session_factory=lambda: SessionLocal(),
        embedding_provider=embedding_provider,
        llm_orchestrator=llm,
        llm_specialist=llm,
        llm_formatter=llm,
        retrieval_context=retrieval_context,
    )
    
    print(f"\nSQL: {final_state.get('sql', 'N/A')[:500]}")
    print(f"Linhas: {final_state.get('num_rows', 0)}")
    print(f"Erro: {final_state.get('error', 'N/A')}")
    print(f"Resposta: {final_state.get('answer', 'N/A')[:300]}")
    
finally:
    db.close()


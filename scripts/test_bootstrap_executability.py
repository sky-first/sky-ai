#!/usr/bin/env python3
"""
Script para testar se as sugestões do bootstrap são realmente executáveis e retornam dados.

Valida que as sugestões geradas podem ser executadas e retornam resultados.
"""

from __future__ import annotations

import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()

# Adicionar o diretório raiz do projeto ao PYTHONPATH
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
from api.routes.connection_query import load_agent_config_from_connection, chat_bootstrap
from api.schemas import ChatBootstrapRequest


# ============== CONFIGURAÇÃO ==============

TEST_SPACE_ID = os.getenv("TEST_SPACE_ID") or "e409079b-5bbf-4249-a769-2010609c30f2"
TEST_CREW_ID: Optional[str] = os.getenv("TEST_CREW_ID") or None
TEST_CONNECTION_ID = os.getenv("TEST_CONNECTION_ID") or "1fd6fee8-bf03-4e82-9c85-419a228ef726"
TEST_USER_ID = os.getenv("TEST_USER_ID") or "00000000-0000-0000-0000-000000000000"


def test_suggestion_executability(question: str, connection_id: str, space_id: str, crew_ids: list[str] = None):
    """Testa se uma sugestão é executável e retorna dados"""
    
    db = SessionLocal()
    
    try:
        # Buscar connection
        with engine.connect() as raw_conn:
            result = raw_conn.execute(
                text("SELECT id, name, connector_id AS type, config FROM data_connections WHERE id = :id"),
                {"id": connection_id}
            ).first()
            
            if not result:
                return {"executable": False, "error": "Connection não encontrada", "num_rows": 0}
            
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
        
        # Criar DataSource
        datasource = DataSourceFactory.build_from_dataconnection(conn)
        
        # Carregar AgentConfig
        agent_config = load_agent_config_from_connection(
            db=db,
            space_id=space_id,
            connection_id=connection_id,
            crew_ids=crew_ids,
        )
        
        # Criar LLM e Embedding providers
        llm = LangChainChatOpenAIProvider(model="gpt-4o-mini", temperature=0.0)
        embedding_provider = OpenAIEmbeddingProvider(model="text-embedding-3-large")
        
        # Criar UserContext
        test_user = User(
            id=UUID(TEST_USER_ID),
            email="test@example.com",
            name="Test User",
            is_active=True
        )
        user_ctx = UserContext(
            user=test_user,
            space_id=UUID(space_id) if space_id else None,
            crew_id=UUID(crew_ids[0]) if crew_ids and len(crew_ids) > 0 else None,
            permissions=[],
        )
        
        # Buscar contexto RAG
        retrieval_context: list[str] = []
        try:
            retrieval_context = build_retrieval_context_for_question(
                db=db,
                embedding_provider=embedding_provider,
                space_id=space_id,
                crew_ids=crew_ids or [],
                question=question,
                top_k=10,
            )
        except Exception:
            retrieval_context = []
        
        # Executar agente
        start_time = time.time()
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
        execution_time = time.time() - start_time
        
        # Analisar resultado
        error = final_state.get("error")
        answer = final_state.get("answer")
        sql = final_state.get("sql")
        num_rows = final_state.get("num_rows", 0)
        
        # Verificar se retornou dados
        has_data = num_rows > 0
        executable = (
            error is None
            and sql is not None
            and answer is not None
            and len(answer.strip()) > 0
        )
        
        # Verificar se a resposta indica "sem dados"
        no_data_indicators = [
            "no data",
            "nenhum dado",
            "sem dados",
            "não encontrado",
            "not found",
            "empty",
            "vazio",
            "sem resultados",
            "no results",
        ]
        answer_lower = (answer or "").lower()
        indicates_no_data = any(indicator in answer_lower for indicator in no_data_indicators)
        
        return {
            "executable": executable,
            "has_data": has_data and not indicates_no_data,
            "num_rows": num_rows,
            "error": error,
            "sql": sql,
            "answer_preview": answer[:200] if answer else None,
            "execution_time": execution_time,
            "indicates_no_data": indicates_no_data,
        }
        
    except Exception as e:
        return {
            "executable": False,
            "has_data": False,
            "error": str(e),
            "num_rows": 0,
            "execution_time": 0,
        }
    finally:
        db.close()


def test_bootstrap_suggestions(is_personal: bool = False):
    """Testa as sugestões geradas pelo bootstrap"""
    
    print("="*80)
    print(f"🧪 TESTE DE EXECUTABILIDADE DAS SUGESTÕES")
    print("="*80)
    print(f"Modo: {'PERSONAL' if is_personal else 'COLLABORATIVE'}")
    print()
    
    db = SessionLocal()
    
    try:
        # Gerar sugestões
        request = ChatBootstrapRequest(
            user_id=TEST_USER_ID,
            space_id=TEST_SPACE_ID,
            is_personal=is_personal,
            language="pt",
            max_suggestions=5,
        )
        
        print("📡 Gerando sugestões...")
        # Usar versão síncrona inline (mesma lógica do chat_bootstrap)
        from core.i18n.i18n import detect_language
        from core.llm.factory import create_llm_orchestrator
        from api.routes.connection_query import (
            _load_connection_metadata_tables,
            _filter_tables_by_permissions,
            _schema_summary_from_tables,
            _fallback_bootstrap,
            _safe_json_loads,
        )
        from api.schemas import ChatBootstrapResponse, ChatBootstrapSuggestion
        from core.logging_utils import log_event
        from core.auth.service import resolve_crew_ids_for_context
        from uuid import UUID
        
        lang = request.language or detect_language(request.user_id or "") or "en"
        lang = (lang or "en").lower()
        if lang not in {"pt", "en", "es"}:
            lang = "en"
        
        # Resolver crew_ids
        resolved_crew_ids = None
        try:
            if request.crew_ids:
                resolved_crew_ids = [str(x) for x in request.crew_ids]
            elif request.user_id:
                resolved = resolve_crew_ids_for_context(
                    db=db,
                    user_id=UUID(request.user_id),
                    space_id=UUID(request.space_id) if request.space_id else None,
                    request_crew_ids=request.crew_ids,
                    is_personal=bool(request.is_personal),
                )
                resolved_crew_ids = [str(x) for x in (resolved or [])]
        except Exception as e:
            log_event(
                "test_bootstrap_resolve_crew_ids_error",
                {
                    "connection_id": TEST_CONNECTION_ID,
                    "space_id": request.space_id,
                    "user_id": request.user_id,
                    "is_personal": bool(request.is_personal),
                    "error": str(e),
                },
            )
            resolved_crew_ids = []
        
        # Carregar e filtrar tabelas
        all_tables = _load_connection_metadata_tables(db=db, connection_id=TEST_CONNECTION_ID)
        if not all_tables:
            response = _fallback_bootstrap(lang=lang, max_suggestions=request.max_suggestions)
        else:
            if request.is_personal:
                tables = all_tables
            else:
                tables = _filter_tables_by_permissions(
                    db=db,
                    connection_id=TEST_CONNECTION_ID,
                    space_id=request.space_id,
                    tables=all_tables,
                    crew_ids=resolved_crew_ids,
                )
            
            if not tables:
                response = _fallback_bootstrap(lang=lang, max_suggestions=request.max_suggestions)
            else:
                max_tables_in_prompt = min(12, len(tables))
                _logical, schema_summary = _schema_summary_from_tables(tables, max_tables=max_tables_in_prompt)
                
                mode_context = ""
                if request.is_personal:
                    mode_context = "The user is in PERSONAL mode and has access to all their data across all crews/spaces."
                else:
                    mode_context = f"The user is in COLLABORATIVE mode and has access only to data from the specific space/crew (space_id: {request.space_id})."
                    if resolved_crew_ids:
                        mode_context += f" They have access to {len(resolved_crew_ids)} crew(s)."
                
                system = (
                    "You generate a greeting and suggestion cards for a data analytics chat.\n"
                    "Rules:\n"
                    "- Output STRICT JSON only.\n"
                    "- JSON schema: {\"greeting\": string, \"suggestions\": [{\"title\": string, \"question\": string}]}\n"
                    "- Provide EXACTLY N suggestions.\n"
                    "- Suggestions must be answerable using ONLY the provided tables/columns.\n"
                    "- Avoid mentioning table physical names; prefer natural questions.\n"
                    "- Keep questions short and actionable.\n"
                    f"- Language: {lang}\n"
                    f"\nContext: {mode_context}\n"
                    "- Generate suggestions that are relevant to the user's accessible data only.\n"
                )
                
                user = (
                    f"N={max(1, request.max_suggestions - 1)}\n"
                    f"User has access to {len(tables)} tables (filtered by permissions). Schema (sample):\n"
                    f"{schema_summary}\n\n"
                    f"Context: {mode_context}\n\n"
                    "Generate greeting + suggestions based ONLY on the accessible tables shown above."
                )
                
                try:
                    llm = create_llm_orchestrator(creativity=15, length=20)
                    resp = llm.invoke(
                        [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ]
                    )
                    parsed = _safe_json_loads(getattr(resp, "content", "") or "")
                    if not isinstance(parsed, dict):
                        response = _fallback_bootstrap(lang=lang, max_suggestions=request.max_suggestions)
                    else:
                        greeting = str(parsed.get("greeting") or "").strip()
                        suggestions_raw = parsed.get("suggestions") or []
                        suggestions: list[ChatBootstrapSuggestion] = []
                        if isinstance(suggestions_raw, list):
                            for item in suggestions_raw:
                                if isinstance(item, dict):
                                    title = str(item.get("title") or "").strip()
                                    question = str(item.get("question") or "").strip()
                                    if title and question:
                                        suggestions.append(ChatBootstrapSuggestion(title=title, kind="question", question=question))
                        
                        if not greeting or len(suggestions) == 0:
                            response = _fallback_bootstrap(lang=lang, max_suggestions=request.max_suggestions)
                        else:
                            # Validar sugestões
                            try:
                                from core.validation.question_validator import QuestionValidator
                                from core.validation.suggestion_validator import SuggestionValidator
                                
                                available_tables_meta = [
                                    {
                                        "name": t.get("name", ""),
                                        "logical_name": t.get("logical_name") or t.get("name", ""),
                                        "columns": [c.get("name") if isinstance(c, dict) else str(c) 
                                                   for c in (t.get("columns") or [])]
                                    }
                                    for t in tables[:max_tables_in_prompt]
                                ]
                                available_columns = {
                                    (t.get("logical_name") or t.get("name", "")): [
                                        c.get("name") if isinstance(c, dict) else str(c) 
                                        for c in (t.get("columns") or [])
                                    ]
                                    for t in tables[:max_tables_in_prompt]
                                }
                                
                                question_validator = QuestionValidator(available_tables_meta, available_columns)
                                suggestion_validator = SuggestionValidator(question_validator)
                                
                                filtered_suggestions: list[ChatBootstrapSuggestion] = []
                                for sug in suggestions:
                                    if sug.kind == "action":
                                        filtered_suggestions.append(sug)
                                        continue
                                    
                                    question_text = sug.question or ""
                                    if question_text:
                                        should_filter = suggestion_validator.should_filter_suggestion(question_text)
                                        if should_filter:
                                            continue
                                    
                                    filtered_suggestions.append(sug)
                                
                                suggestions = filtered_suggestions
                            except Exception:
                                pass
                            
                            # Always prepend the action card
                            action_title = "Create dashboard" if lang == "en" else ("Criar dashboard" if lang == "pt" else "Crear dashboard")
                            action_card = ChatBootstrapSuggestion(
                                title=action_title,
                                kind="action",
                                action_id="create_dashboard",
                                payload={"default_goal": "Billing overview", "default_max_widgets": 6},
                            )
                            suggestions = [action_card] + suggestions
                            
                            # Normalize count
                            suggestions = suggestions[: request.max_suggestions]
                            while len(suggestions) < request.max_suggestions:
                                suggestions.append(
                                    ChatBootstrapSuggestion(title="Example", kind="question", question=(suggestions[-1].question or "Show me something interesting from my data."))
                                )
                            
                            response = ChatBootstrapResponse(
                                greeting=greeting,
                                suggestions=suggestions,
                                meta={
                                    "fallback": False,
                                    "num_tables": len(tables),
                                    "num_tables_total": len(all_tables),
                                    "prompt_tables": max_tables_in_prompt,
                                    "agent_id": None,
                                    "is_personal": bool(request.is_personal),
                                    "crew_ids": resolved_crew_ids,
                                    "mode": "personal" if request.is_personal else "collaborative",
                                },
                            )
                except Exception:
                    response = _fallback_bootstrap(lang=lang, max_suggestions=request.max_suggestions)
        
        print(f"✅ {len(response.suggestions)} sugestões geradas")
        print()
        
        # Resolver crew_ids para teste
        from core.auth.service import resolve_crew_ids_for_context
        resolved_crew_ids = []
        try:
            resolved = resolve_crew_ids_for_context(
                db=db,
                user_id=UUID(TEST_USER_ID),
                space_id=UUID(TEST_SPACE_ID) if TEST_SPACE_ID else None,
                request_crew_ids=None,
                is_personal=is_personal,
            )
            resolved_crew_ids = [str(x) for x in (resolved or [])]
        except Exception:
            resolved_crew_ids = []
        
        # Testar cada sugestão
        print("="*80)
        print("📝 TESTANDO SUGESTÕES:")
        print("="*80)
        print()
        
        results = []
        for i, suggestion in enumerate(response.suggestions, 1):
            if suggestion.kind == "action":
                print(f"[{i}] [AÇÃO] {suggestion.title}")
                print("   ⏭️  Pulando (ação não precisa validação)")
                print()
                continue
            
            question = suggestion.question or ""
            if not question:
                print(f"[{i}] {suggestion.title}")
                print("   ⚠️  Sem pergunta para testar")
                print()
                continue
            
            print(f"[{i}] {suggestion.title}")
            print(f"   Pergunta: {question}")
            
            result = test_suggestion_executability(
                question=question,
                connection_id=TEST_CONNECTION_ID,
                space_id=TEST_SPACE_ID,
                crew_ids=resolved_crew_ids,
            )
            
            results.append({
                "title": suggestion.title,
                "question": question,
                **result,
            })
            
            if result["executable"] and result["has_data"]:
                print(f"   ✅ EXECUTÁVEL - {result['num_rows']} linhas retornadas ({result['execution_time']:.2f}s)")
            elif result["executable"] and not result["has_data"]:
                print(f"   ⚠️  EXECUTÁVEL MAS SEM DADOS - {result['num_rows']} linhas ({result['execution_time']:.2f}s)")
                if result.get("answer_preview"):
                    print(f"   Resposta: {result['answer_preview']}")
            else:
                print(f"   ❌ NÃO EXECUTÁVEL - {result.get('error', 'Erro desconhecido')}")
            
            print()
            time.sleep(0.5)  # Pausa entre testes
        
        # Resumo
        print("="*80)
        print("📊 RESUMO")
        print("="*80)
        
        questions = [r for r in results if r.get("question")]
        executable_with_data = [r for r in questions if r.get("executable") and r.get("has_data")]
        executable_no_data = [r for r in questions if r.get("executable") and not r.get("has_data")]
        not_executable = [r for r in questions if not r.get("executable")]
        
        print(f"Total de perguntas testadas: {len(questions)}")
        print(f"✅ Executáveis com dados: {len(executable_with_data)} ({len(executable_with_data)/len(questions)*100:.1f}%)")
        print(f"⚠️  Executáveis sem dados: {len(executable_no_data)} ({len(executable_no_data)/len(questions)*100:.1f}%)")
        print(f"❌ Não executáveis: {len(not_executable)} ({len(not_executable)/len(questions)*100:.1f}%)")
        print()
        
        if executable_no_data:
            print("⚠️  SUGESTÕES QUE RETORNAM SEM DADOS:")
            for r in executable_no_data:
                print(f"  - {r['title']}: {r['question']}")
                print(f"    Resposta: {r.get('answer_preview', 'N/A')[:100]}")
            print()
        
        if not_executable:
            print("❌ SUGESTÕES NÃO EXECUTÁVEIS:")
            for r in not_executable:
                print(f"  - {r['title']}: {r['question']}")
                print(f"    Erro: {r.get('error', 'N/A')[:100]}")
            print()
        
        return {
            "total": len(questions),
            "executable_with_data": len(executable_with_data),
            "executable_no_data": len(executable_no_data),
            "not_executable": len(not_executable),
            "results": results,
        }
        
    except Exception as e:
        print(f"❌ ERRO: {str(e)}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        db.close()


def main():
    """Função principal"""
    print("="*80)
    print("🧪 TESTE DE EXECUTABILIDADE DAS SUGESTÕES DO BOOTSTRAP")
    print("="*80)
    print()
    
    # Testar modo Collaborative primeiro (mais restritivo)
    print("Testando modo COLLABORATIVE...")
    result_collab = test_bootstrap_suggestions(is_personal=False)
    
    print("\n" + "="*80)
    print("Testando modo PERSONAL...")
    result_personal = test_bootstrap_suggestions(is_personal=True)
    
    # Comparação final
    if result_collab and result_personal:
        print("\n" + "="*80)
        print("📊 COMPARAÇÃO FINAL")
        print("="*80)
        print(f"Modo Collaborative:")
        print(f"  ✅ Com dados: {result_collab['executable_with_data']}/{result_collab['total']}")
        print(f"  ⚠️  Sem dados: {result_collab['executable_no_data']}/{result_collab['total']}")
        print(f"Modo Personal:")
        print(f"  ✅ Com dados: {result_personal['executable_with_data']}/{result_personal['total']}")
        print(f"  ⚠️  Sem dados: {result_personal['executable_no_data']}/{result_personal['total']}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())


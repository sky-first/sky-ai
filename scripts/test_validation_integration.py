#!/usr/bin/env python3
"""
Script para testar a integração do QuestionValidator no orchestrator.

Testa se perguntas problemáticas são bloqueadas antes de gerar SQL.
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
from api.routes.connection_query import load_agent_config_from_connection


# ============== CONFIGURAÇÃO ==============

TEST_SPACE_ID = os.getenv("TEST_SPACE_ID") or "e409079b-5bbf-4249-a769-2010609c30f2"
TEST_CREW_ID: Optional[str] = os.getenv("TEST_CREW_ID") or None
TEST_CONNECTION_ID = os.getenv("TEST_CONNECTION_ID") or "1fd6fee8-bf03-4e82-9c85-419a228ef726"
TEST_USER_ID = os.getenv("TEST_USER_ID") or "00000000-0000-0000-0000-000000000000"


def test_question(question: str, should_block: bool = False):
    """Testa uma pergunta e verifica se foi bloqueada corretamente"""
    print(f"\n{'='*80}")
    print(f"🧪 TESTANDO: {question}")
    print(f"{'='*80}")
    print(f"Esperado: {'BLOQUEAR' if should_block else 'PERMITIR'}")
    
    db = SessionLocal()
    
    try:
        # Buscar connection
        with engine.connect() as raw_conn:
            result = raw_conn.execute(
                text("SELECT id, name, connector_id AS type, config FROM data_connections WHERE id = :id"),
                {"id": TEST_CONNECTION_ID}
            ).first()
            
            if not result:
                print("❌ Connection não encontrada")
                return False
            
            import json
            config_data = result[3] if isinstance(result[3], dict) else json.loads(result[3]) if isinstance(result[3], str) else {}
            
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
            space_id=TEST_SPACE_ID,
            connection_id=TEST_CONNECTION_ID,
            crew_ids=[TEST_CREW_ID] if TEST_CREW_ID else None,
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
            space_id=UUID(TEST_SPACE_ID) if TEST_SPACE_ID else None,
            crew_id=UUID(TEST_CREW_ID) if TEST_CREW_ID else None,
            permissions=[],
        )
        
        # Buscar contexto RAG
        retrieval_context: list[str] = []
        try:
            retrieval_context = build_retrieval_context_for_question(
                db=db,
                embedding_provider=embedding_provider,
                space_id=TEST_SPACE_ID,
                crew_ids=[TEST_CREW_ID] if TEST_CREW_ID else [],
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
        
        print(f"⏱️  Tempo: {execution_time:.2f}s")
        
        # Verificar se foi bloqueado
        was_blocked = bool(error and ("MULTIPLE_QUERIES_RISK" in error or "AMBIGUOUS_QUESTION" in error))
        
        if was_blocked:
            print(f"🚫 BLOQUEADO: {error}")
            if answer:
                print(f"📝 Resposta: {answer[:200]}")
        else:
            if error:
                print(f"❌ ERRO (não esperado): {error}")
            elif sql:
                print(f"✅ SQL gerado: {sql[:200]}...")
                print(f"✅ Resposta: {answer[:200] if answer else 'N/A'}...")
            else:
                print(f"⚠️  Sem SQL gerado")
        
        # Validar resultado
        if should_block:
            success = was_blocked
            status = "✅" if success else "❌"
            print(f"{status} {'Bloqueado corretamente' if success else 'Deveria ter sido bloqueado mas não foi'}")
        else:
            success = not was_blocked and (sql or answer)
            status = "✅" if success else "❌"
            print(f"{status} {'Permitido corretamente' if success else 'Deveria ter sido permitido mas foi bloqueado ou falhou'}")
        
        return success
        
    except Exception as e:
        print(f"❌ EXCEÇÃO: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def main():
    """Função principal"""
    print("="*80)
    print("🧪 TESTE DE INTEGRAÇÃO - VALIDAÇÃO NO ORCHESTRATOR")
    print("="*80)
    print(f"Space ID: {TEST_SPACE_ID}")
    print(f"Connection ID: {TEST_CONNECTION_ID}")
    print()
    
    # Casos de teste
    test_cases = [
        {
            "question": "Primeiro mostre as faturas e depois os pagamentos",
            "should_block": True,
            "description": "Pergunta que deve ser bloqueada (múltiplas queries)",
        },
        {
            "question": "Quais são os valores de créditos por cliente?",
            "should_block": False,
            "description": "Pergunta válida que deve ser permitida",
        },
        {
            "question": "Quais itens foram vendidos em uma fatura específica?",
            "should_block": False,  # Warning, não bloqueia
            "description": "Pergunta ambígua (gera warning mas não bloqueia)",
        },
        {
            "question": "Qual é o total de pagamentos por mês?",
            "should_block": False,
            "description": "Pergunta válida que deve ser permitida",
        },
    ]
    
    results = []
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n[{i}/{len(test_cases)}] {test_case['description']}")
        success = test_question(
            question=test_case["question"],
            should_block=test_case["should_block"],
        )
        results.append({
            "test": test_case["description"],
            "success": success,
        })
        time.sleep(0.5)  # Pausa entre testes
    
    # Resumo
    print("\n" + "="*80)
    print("📊 RESUMO")
    print("="*80)
    
    passed = sum(1 for r in results if r["success"])
    failed = len(results) - passed
    
    print(f"Total: {len(results)}")
    print(f"✅ Passou: {passed}")
    print(f"❌ Falhou: {failed}")
    
    if failed > 0:
        print("\n❌ TESTES QUE FALHARAM:")
        for r in results:
            if not r["success"]:
                print(f"  - {r['test']}")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())


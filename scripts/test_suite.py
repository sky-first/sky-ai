#!/usr/bin/env python3
"""
Script de Testes Automatizados para Ambiente de Testing

Executa uma suíte completa de testes do pipeline de IA:
- Testa múltiplas perguntas de negócio
- Valida SQL gerado
- Valida respostas da IA
- Gera relatório de testes
- Pode ser usado em CI/CD

Uso:
    python3 scripts/test_suite.py
    
Variáveis de ambiente:
    TEST_SPACE_ID: ID do Space de teste
    TEST_CONNECTION_ID: ID da Connection de teste
    TEST_QUESTION: Pergunta única (opcional, sobrescreve a suíte)
"""

from __future__ import annotations

import os
import sys
import json
import time
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

from dotenv import load_dotenv
load_dotenv()

# Adicionar o diretório raiz do projeto ao PYTHONPATH
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from sqlalchemy.orm import Session
from sqlalchemy import text

from db.base import SessionLocal
from core.data_sources.factory import DataSourceFactory
from core.llm.providers import LangChainChatOpenAIProvider
from core.agents.generic_sql_agent import (
    AgentConfig,
    TableSchema,
    build_generic_sql_graph,
    AgentState,
)
from core.rag.context_retrieval import build_retrieval_context_for_question
from core.rag.embeddings import OpenAIEmbeddingProvider


# ============== CONFIGURAÇÃO ==============

TEST_SPACE_ID = os.getenv("TEST_SPACE_ID") or "00000000-0000-0000-0000-000000000001"
TEST_CREW_ID: Optional[str] = os.getenv("TEST_CREW_ID") or None
TEST_CONNECTION_ID = os.getenv("TEST_CONNECTION_ID") or "00000000-0000-0000-0000-000000000002"

# Suíte de testes padrão
DEFAULT_TEST_QUESTIONS = [
    {
        "question": "Qual é a performance de pageviews mensal?",
        "expected_table": None,  # Será detectado automaticamente
        "expected_keywords": ["pageviews", "mensal", "performance"],
        "description": "Teste de análise de performance mensal de pageviews"
    },
    {
        "question": "Como se distribui o tráfego por dispositivo?",
        "expected_table": None,  # Será detectado automaticamente
        "expected_keywords": ["tráfego", "dispositivo", "distribui"],
        "description": "Teste de distribuição de tráfego por dispositivo"
    },
    {
        "question": "Quais países geram mais tráfego?",
        "expected_table": None,  # Será detectado automaticamente
        "expected_keywords": ["países", "tráfego", "mais"],
        "description": "Teste de ranking de países por tráfego"
    },
]


@dataclass
class TestResult:
    """Resultado de um teste individual"""
    question: str
    description: str
    success: bool
    error: Optional[str] = None
    sql_generated: Optional[str] = None
    answer: Optional[str] = None
    chosen_table: Optional[str] = None
    execution_time: float = 0.0
    expected_table: Optional[str] = None
    validation_errors: List[str] = None
    
    def __post_init__(self):
        if self.validation_errors is None:
            self.validation_errors = []


@dataclass
class TestSuiteResult:
    """Resultado completo da suíte de testes"""
    total_tests: int
    passed_tests: int
    failed_tests: int
    total_time: float
    results: List[TestResult]
    timestamp: str
    environment: Dict[str, str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": {
                "total": self.total_tests,
                "passed": self.passed_tests,
                "failed": self.failed_tests,
                "success_rate": f"{(self.passed_tests / self.total_tests * 100):.1f}%" if self.total_tests > 0 else "0%",
                "total_time_seconds": round(self.total_time, 2)
            },
            "timestamp": self.timestamp,
            "environment": self.environment,
            "results": [asdict(r) for r in self.results]
        }


def load_agent_config(
    db: Session,
    space_id: str,
    crew_id: str | None,
    conn_id: str,
) -> AgentConfig:
    """Carrega TableMetadata e monta AgentConfig"""
    from sqlalchemy import text
    from db.base import engine
    
    # Buscar metadados via SQL direto (compatível com UUID)
    with engine.connect() as raw_conn:
        result = raw_conn.execute(
            text("""
                SELECT table_name, column_name, data_type, is_nullable
                FROM table_metadata
                WHERE space_id = :space_id AND data_connection_id = :conn_id
                ORDER BY table_name, column_name
            """),
            {"space_id": space_id, "conn_id": conn_id}
        ).fetchall()
    
    if not result:
        raise RuntimeError("Nenhum metadata encontrado para este Space/Connection")
    
    # Agrupar por tabela
    tables: Dict[str, List] = {}
    for row in result:
        table_name = row[0]
        if table_name not in tables:
            tables[table_name] = []
        tables[table_name].append({
            "column_name": row[1],
            "data_type": row[2] or "STRING",
            "is_nullable": row[3] or False
        })
    
    # Detectar dataset baseado no nome da tabela
    def detect_dataset(table_name: str) -> str:
        """Detecta o dataset correto baseado no nome da tabela"""
        # Tabelas do web_silver
        web_tables = [
            "silver_events_enriquecido",
            "silver_pageviews_enriquecido", 
            "silver_sessions_enriquecido",
            "silver_sources_enriquecido",
            "silver_users_enriquecido",
            "silver_web_data_enriquecido"
        ]
        if table_name in web_tables:
            return "data-mesh-gcp.web_silver"
        # Tabelas do billing_silver (padrão)
        return "data-mesh-gcp.billing_silver"
    
    # Criar TableSchemas
    table_schemas: List[TableSchema] = []
    for tname, cols in tables.items():
        # Detectar dataset correto para esta tabela
        dataset = detect_dataset(tname)
        physical_name = f"{dataset}.{tname}" if "." not in tname else tname
        schema = TableSchema(
            logical_name=tname,
            physical_name=physical_name,
            columns=[
                {
                    "name": c["column_name"],
                    "type": c["data_type"],
                    "nullable": c["is_nullable"]
                }
                for c in cols
            ],
        )
        table_schemas.append(schema)
    
    return AgentConfig(
        id=f"agent-test-{conn_id}",
        name="Agent Test Suite",
        tables=table_schemas,
    )


def run_single_test(
    question: str,
    expected_table: Optional[str] = None,
    expected_keywords: Optional[List[str]] = None,
    description: str = "",
) -> TestResult:
    """Executa um teste individual"""
    start_time = time.time()
    
    db = SessionLocal()
    
    try:
        # Buscar connection
        from sqlalchemy import text
        from db.base import engine
        
        with engine.connect() as raw_conn:
            result = raw_conn.execute(
                text("SELECT id, name, connector_id, config FROM data_connections WHERE id = :id"),
                {"id": TEST_CONNECTION_ID}
            ).first()
            
            if not result:
                raise RuntimeError("DataConnection não encontrada")
            
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
        agent_config = load_agent_config(db, TEST_SPACE_ID, TEST_CREW_ID, conn.id)
        
        # Criar LLM e Embedding providers
        llm = LangChainChatOpenAIProvider(model="gpt-4o", temperature=0.0)
        embedding_provider = OpenAIEmbeddingProvider(model="text-embedding-3-large")
        
        # Tentar RAG (opcional)
        try:
            retrieval_context = build_retrieval_context_for_question(
                db=db,
                embedding_provider=embedding_provider,
                space_id=TEST_SPACE_ID,
                crew_ids=[TEST_CREW_ID] if TEST_CREW_ID else [],
                question=question,
                top_k=5,
            )
        except Exception:
            retrieval_context = []
        
        # Montar graph
        def db_session_factory():
            return SessionLocal()
        
        graph = build_generic_sql_graph(
            agent_config=agent_config,
            data_source=datasource,
            db_session_factory=db_session_factory,
            embedding_provider=embedding_provider,
            llm_orchestrator=llm,
            llm_specialist=llm,
            llm_formatter=llm,
        )
        
        # Executar
        initial_state: AgentState = {
            "question": question,
            "retrieval_context": retrieval_context,
        }
        
        final_state = graph.invoke(
            initial_state,
            config={"configurable": {"thread_id": f"test-{int(time.time())}"}},
        )
        
        execution_time = time.time() - start_time
        
        # Validar resultado
        sql_generated = final_state.get("sql")
        answer = final_state.get("answer")
        error = final_state.get("error")
        chosen_table = final_state.get("chosen_table")
        
        validation_errors = []
        success = True
        
        if error:
            success = False
            validation_errors.append(f"Erro na execução: {error}")
        
        if not sql_generated:
            success = False
            validation_errors.append("SQL não foi gerado")
        
        if not answer:
            success = False
            validation_errors.append("Resposta não foi gerada")
        
        if expected_table and chosen_table != expected_table:
            validation_errors.append(
                f"Tabela escolhida ({chosen_table}) diferente da esperada ({expected_table})"
            )
            # Não falha o teste, apenas avisa
        
        if expected_keywords:
            answer_lower = (answer or "").lower()
            missing_keywords = [kw for kw in expected_keywords if kw.lower() not in answer_lower]
            if missing_keywords:
                validation_errors.append(
                    f"Palavras-chave não encontradas na resposta: {missing_keywords}"
                )
                # Não falha o teste, apenas avisa
        
        return TestResult(
            question=question,
            description=description,
            success=success,
            error=error,
            sql_generated=sql_generated,
            answer=answer,
            chosen_table=chosen_table,
            execution_time=execution_time,
            expected_table=expected_table,
            validation_errors=validation_errors
        )
        
    except Exception as e:
        execution_time = time.time() - start_time
        return TestResult(
            question=question,
            description=description,
            success=False,
            error=str(e),
            execution_time=execution_time,
            expected_table=expected_table,
            validation_errors=[f"Exceção: {str(e)}"]
        )
    finally:
        db.close()


def run_test_suite(questions: Optional[List[Dict[str, Any]]] = None) -> TestSuiteResult:
    """Executa a suíte completa de testes"""
    if questions is None:
        questions = DEFAULT_TEST_QUESTIONS
    
    # Se houver TEST_QUESTION no env, usar apenas ela
    if os.getenv("TEST_QUESTION"):
        questions = [{
            "question": os.getenv("TEST_QUESTION"),
            "expected_table": None,
            "expected_keywords": None,
            "description": "Teste via variável de ambiente"
        }]
    
    start_time = time.time()
    results: List[TestResult] = []
    
    print("=" * 80)
    print("🧪 EXECUTANDO SUÍTE DE TESTES")
    print("=" * 80)
    print(f"Space ID: {TEST_SPACE_ID}")
    print(f"Connection ID: {TEST_CONNECTION_ID}")
    print(f"Total de testes: {len(questions)}\n")
    
    for i, test_case in enumerate(questions, 1):
        print(f"\n[{i}/{len(questions)}] Testando: {test_case['question']}")
        print(f"   Descrição: {test_case.get('description', 'N/A')}")
        
        result = run_single_test(
            question=test_case["question"],
            expected_table=test_case.get("expected_table"),
            expected_keywords=test_case.get("expected_keywords"),
            description=test_case.get("description", ""),
        )
        
        results.append(result)
        
        if result.success:
            print(f"   ✅ PASSOU ({result.execution_time:.2f}s)")
            if result.chosen_table:
                print(f"   📊 Tabela escolhida: {result.chosen_table}")
        else:
            print(f"   ❌ FALHOU ({result.execution_time:.2f}s)")
            if result.error:
                print(f"   ⚠️  Erro: {result.error[:200]}")
            if result.validation_errors:
                for ve in result.validation_errors:
                    print(f"   ⚠️  {ve}")
    
    total_time = time.time() - start_time
    passed = sum(1 for r in results if r.success)
    failed = len(results) - passed
    
    suite_result = TestSuiteResult(
        total_tests=len(results),
        passed_tests=passed,
        failed_tests=failed,
        total_time=total_time,
        results=results,
        timestamp=datetime.now(timezone.utc).isoformat(),
        environment={
            "TEST_SPACE_ID": TEST_SPACE_ID,
            "TEST_CONNECTION_ID": TEST_CONNECTION_ID,
            "TEST_CREW_ID": TEST_CREW_ID or "None",
        }
    )
    
    return suite_result


def print_summary(result: TestSuiteResult):
    """Imprime resumo dos testes"""
    print("\n" + "=" * 80)
    print("📊 RESUMO DOS TESTES")
    print("=" * 80)
    print(f"Total de testes: {result.total_tests}")
    print(f"✅ Passou: {result.passed_tests}")
    print(f"❌ Falhou: {result.failed_tests}")
    print(f"⏱️  Tempo total: {result.total_time:.2f}s")
    print(f"📈 Taxa de sucesso: {(result.passed_tests / result.total_tests * 100):.1f}%" if result.total_tests > 0 else "0%")
    
    if result.failed_tests > 0:
        print("\n❌ TESTES QUE FALHARAM:")
        for r in result.results:
            if not r.success:
                print(f"\n  Pergunta: {r.question}")
                if r.error:
                    print(f"  Erro: {r.error[:200]}")
                if r.validation_errors:
                    for ve in r.validation_errors:
                        print(f"  - {ve}")
    
    print("\n" + "=" * 80)


def save_json_report(result: TestSuiteResult, filename: str = "test_report.json"):
    """Salva relatório em JSON"""
    report_path = os.path.join(os.path.dirname(__file__), "..", filename)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
    print(f"\n📄 Relatório JSON salvo em: {report_path}")


def main():
    """Função principal"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Executa suíte de testes do pipeline de IA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  # Executar todos os testes padrão
  python3 scripts/test_suite.py
  
  # Executar teste único via variável de ambiente
  TEST_QUESTION="Quantos clientes temos?" python3 scripts/test_suite.py
  
  # Salvar relatório em arquivo específico
  python3 scripts/test_suite.py --report custom_report.json
  
  # Modo verbose (mostra mais detalhes)
  python3 scripts/test_suite.py --verbose
        """
    )
    parser.add_argument(
        "--report",
        default="test_report.json",
        help="Nome do arquivo de relatório JSON (padrão: test_report.json)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Modo verbose - mostra mais detalhes de cada teste"
    )
    parser.add_argument(
        "--question",
        help="Pergunta única para testar (sobrescreve suíte padrão)"
    )
    
    args = parser.parse_args()
    
    try:
        # Se --question foi fornecido, usar apenas essa pergunta
        questions = None
        if args.question:
            questions = [{
                "question": args.question,
                "expected_table": None,
                "expected_keywords": None,
                "description": f"Teste via argumento: {args.question}"
            }]
        
        result = run_test_suite(questions)
        
        if args.verbose:
            print("\n" + "=" * 80)
            print("📋 DETALHES DOS TESTES")
            print("=" * 80)
            for i, r in enumerate(result.results, 1):
                print(f"\n[{i}] {r.question}")
                print(f"    Status: {'✅ PASSOU' if r.success else '❌ FALHOU'}")
                print(f"    Tempo: {r.execution_time:.2f}s")
                if r.sql_generated:
                    print(f"    SQL: {r.sql_generated[:100]}...")
                if r.answer:
                    print(f"    Resposta: {r.answer[:150]}...")
                if r.chosen_table:
                    print(f"    Tabela escolhida: {r.chosen_table}")
                if r.validation_errors:
                    for ve in r.validation_errors:
                        print(f"    ⚠️  {ve}")
        
        print_summary(result)
        
        # Salvar relatório JSON
        save_json_report(result, args.report)
        
        # Exit code baseado no resultado (padrão para CI/CD)
        exit_code = 1 if result.failed_tests > 0 else 0
        sys.exit(exit_code)
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Testes interrompidos pelo usuário")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ ERRO FATAL na execução dos testes: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()





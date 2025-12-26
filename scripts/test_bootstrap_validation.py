#!/usr/bin/env python3
"""
Script para testar a validação de sugestões no endpoint de bootstrap.

Verifica se sugestões problemáticas são filtradas corretamente.
"""

from __future__ import annotations

import os
import sys
import json

from dotenv import load_dotenv
load_dotenv()

# Adicionar o diretório raiz do projeto ao PYTHONPATH
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from sqlalchemy import text
from db.base import SessionLocal, engine
from api.routes.connection_query import chat_bootstrap
from api.schemas import ChatBootstrapRequest


# ============== CONFIGURAÇÃO ==============

TEST_SPACE_ID = os.getenv("TEST_SPACE_ID") or "e409079b-5bbf-4249-a769-2010609c30f2"
TEST_CONNECTION_ID = os.getenv("TEST_CONNECTION_ID") or "1fd6fee8-bf03-4e82-9c85-419a228ef726"
TEST_USER_ID = os.getenv("TEST_USER_ID") or "00000000-0000-0000-0000-000000000000"


def test_bootstrap_validation():
    """Testa se o bootstrap filtra sugestões problemáticas"""
    print("="*80)
    print("🧪 TESTE DE VALIDAÇÃO NO BOOTSTRAP")
    print("="*80)
    print(f"Connection ID: {TEST_CONNECTION_ID}")
    print()
    
    db = SessionLocal()
    
    try:
        # Chamar endpoint de bootstrap
        request = ChatBootstrapRequest(
            user_id=TEST_USER_ID,
            space_id=TEST_SPACE_ID,
            language="pt",
            max_suggestions=5,
        )
        
        print("📡 Chamando endpoint de bootstrap...")
        # Criar uma versão síncrona da função
        from core.i18n.i18n import detect_language
        from core.llm.factory import create_llm_orchestrator
        from api.routes.connection_query import (
            _load_connection_metadata_tables,
            _schema_summary_from_tables,
            _fallback_bootstrap,
            _safe_json_loads,
        )
        from api.schemas import ChatBootstrapResponse, ChatBootstrapSuggestion
        from core.logging_utils import log_event
        
        lang = request.language or detect_language(request.user_id or "") or "en"
        lang = (lang or "en").lower()
        if lang not in {"pt", "en", "es"}:
            lang = "en"
        
        # Backend-compatible: read catalog from `connection_metadata`.
        tables = _load_connection_metadata_tables(db=db, connection_id=TEST_CONNECTION_ID)
        if not tables:
            response = _fallback_bootstrap(lang=lang, max_suggestions=request.max_suggestions)
        else:
            # Build a compact schema summary for the LLM.
            max_tables_in_prompt = min(12, len(tables))
            _logical, schema_summary = _schema_summary_from_tables(tables, max_tables=max_tables_in_prompt)
            
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
            )
            
            user = (
                f"N={max(1, request.max_suggestions - 1)}\n"
                f"User has access to {len(tables)} tables. Schema (sample):\n"
                f"{schema_summary}\n\n"
                "Generate greeting + suggestions."
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
                        # ✅ NOVA: Validar e filtrar sugestões problemáticas usando SuggestionValidator
                        try:
                            from core.validation.question_validator import QuestionValidator
                            from core.validation.suggestion_validator import SuggestionValidator
                            
                            # Preparar metadados para o validador
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
                            
                            # Filtrar sugestões problemáticas
                            filtered_suggestions: list[ChatBootstrapSuggestion] = []
                            filtered_count = 0
                            
                            for sug in suggestions:
                                # Ações (como "Create dashboard") não precisam validação
                                if sug.kind == "action":
                                    filtered_suggestions.append(sug)
                                    continue
                                
                                # Validar perguntas
                                question_text = sug.question or ""
                                if question_text:
                                    should_filter = suggestion_validator.should_filter_suggestion(question_text)
                                    if should_filter:
                                        filtered_count += 1
                                        log_event(
                                            "bootstrap_suggestion_filtered",
                                            {
                                                "connection_id": TEST_CONNECTION_ID,
                                                "title": sug.title,
                                                "question": question_text[:200],
                                                "reason": "Failed validation",
                                            },
                                        )
                                        continue  # Pular esta sugestão
                                
                                filtered_suggestions.append(sug)
                            
                            suggestions = filtered_suggestions
                            
                            # Se filtramos muitas sugestões, adicionar algumas de fallback
                            if filtered_count > 0 and len(suggestions) < request.max_suggestions:
                                log_event(
                                    "bootstrap_suggestions_filtered_summary",
                                    {
                                        "connection_id": TEST_CONNECTION_ID,
                                        "filtered_count": filtered_count,
                                        "remaining_count": len(suggestions),
                                        "requested_count": request.max_suggestions,
                                    },
                                )
                        except Exception as e:
                            # Se a validação falhar, não quebra o fluxo - apenas loga
                            log_event(
                                "bootstrap_validation_exception",
                                {
                                    "connection_id": TEST_CONNECTION_ID,
                                    "error": str(e)[:500],
                                },
                            )
                            # Continua normalmente sem validação
                        
                        # Always prepend the action card as the first suggestion.
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
                                "prompt_tables": max_tables_in_prompt,
                                "agent_id": None,
                            },
                        )
            except Exception:
                response = _fallback_bootstrap(lang=lang, max_suggestions=request.max_suggestions)
        
        print(f"✅ Greeting: {response.greeting[:100]}...")
        print(f"✅ Total de sugestões: {len(response.suggestions)}")
        print()
        
        # Analisar sugestões
        print("📝 ANÁLISE DAS SUGESTÕES:")
        print("="*80)
        
        actions = [s for s in response.suggestions if s.kind == "action"]
        questions = [s for s in response.suggestions if s.kind == "question"]
        
        print(f"Ações: {len(actions)}")
        for action in actions:
            print(f"  - [{action.kind}] {action.title}")
        
        print(f"\nPerguntas: {len(questions)}")
        for i, question in enumerate(questions, 1):
            print(f"\n  {i}. {question.title}")
            print(f"     Pergunta: {question.question}")
            
            # Validar manualmente para verificar se passou
            from core.validation.question_validator import QuestionValidator, ValidationSeverity
            from core.validation.suggestion_validator import SuggestionValidator
            
            # Carregar metadados
            with engine.connect() as raw_conn:
                tables_data = raw_conn.execute(
                    text("SELECT tables FROM connection_metadata WHERE connection_id = CAST(:cid AS uuid) LIMIT 1"),
                    {"cid": TEST_CONNECTION_ID},
                ).scalar_one_or_none()
            
            if tables_data and isinstance(tables_data, list):
                available_tables_meta = [
                    {
                        "name": t.get("name", ""),
                        "logical_name": t.get("logical_name") or t.get("name", ""),
                        "columns": [c.get("name") if isinstance(c, dict) else str(c) 
                                   for c in (t.get("columns") or [])]
                    }
                    for t in tables_data[:12]
                ]
                available_columns = {
                    (t.get("logical_name") or t.get("name", "")): [
                        c.get("name") if isinstance(c, dict) else str(c) 
                        for c in (t.get("columns") or [])
                    ]
                    for t in tables_data[:12]
                }
                
                validator = QuestionValidator(available_tables_meta, available_columns)
                suggestion_validator = SuggestionValidator(validator)
                
                is_valid, issues = suggestion_validator.validate_suggestion(question.question or "")
                should_filter = suggestion_validator.should_filter_suggestion(question.question or "")
                score = suggestion_validator.get_suggestion_score(question.question or "")
                
                if should_filter:
                    print(f"     ⚠️  PROBLEMA: Esta sugestão deveria ter sido filtrada!")
                    print(f"     Issues: {len(issues)}")
                    for issue in issues:
                        print(f"       - [{issue.severity.value}] {issue.code}: {issue.message}")
                else:
                    print(f"     ✅ Válida (score: {score:.2f})")
                    if issues:
                        print(f"     ⚠️  Warnings: {len([i for i in issues if i.severity == ValidationSeverity.WARNING])}")
        
        print("\n" + "="*80)
        print("📊 RESUMO")
        print("="*80)
        print(f"Total de sugestões: {len(response.suggestions)}")
        print(f"  - Ações: {len(actions)}")
        print(f"  - Perguntas: {len(questions)}")
        print(f"Meta: {json.dumps(response.meta, indent=2, default=str)}")
        
        return True
        
    except Exception as e:
        print(f"❌ ERRO: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def main():
    """Função principal"""
    success = test_bootstrap_validation()
    
    if success:
        print("\n✅ Teste concluído com sucesso!")
        return 0
    else:
        print("\n❌ Teste falhou!")
        return 1


if __name__ == "__main__":
    sys.exit(main())


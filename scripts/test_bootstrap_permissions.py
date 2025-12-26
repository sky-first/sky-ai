#!/usr/bin/env python3
"""
Script para testar o bootstrap com diferentes modos de permissão.

Testa:
1. Modo Personal (is_personal=True) - todas as tabelas
2. Modo Collaborative (is_personal=False) - apenas tabelas permitidas
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


def test_bootstrap_mode(is_personal: bool, mode_name: str):
    """Testa o bootstrap em um modo específico"""
    print("="*80)
    print(f"🧪 TESTE: Modo {mode_name}")
    print("="*80)
    print(f"is_personal: {is_personal}")
    print()
    
    db = SessionLocal()
    
    try:
        # Chamar endpoint de bootstrap
        request = ChatBootstrapRequest(
            user_id=TEST_USER_ID,
            space_id=TEST_SPACE_ID,
            is_personal=is_personal,
            language="pt",
            max_suggestions=5,
        )
        
        print("📡 Chamando endpoint de bootstrap...")
        # Criar uma versão síncrona da função
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
        
        print(f"✅ Crew IDs resolvidos: {resolved_crew_ids}")
        
        # Carregar todas as tabelas
        all_tables = _load_connection_metadata_tables(db=db, connection_id=TEST_CONNECTION_ID)
        print(f"📊 Total de tabelas no catálogo: {len(all_tables)}")
        
        if not all_tables:
            response = _fallback_bootstrap(lang=lang, max_suggestions=request.max_suggestions)
        else:
            # Filtrar por permissões
            if request.is_personal:
                tables = all_tables
                print(f"✅ Modo Personal: usando todas as {len(tables)} tabelas")
            else:
                tables = _filter_tables_by_permissions(
                    db=db,
                    connection_id=TEST_CONNECTION_ID,
                    space_id=request.space_id,
                    tables=all_tables,
                    crew_ids=resolved_crew_ids,
                )
                print(f"✅ Modo Collaborative: {len(tables)} tabelas após filtro (de {len(all_tables)} total)")
            
            if not tables:
                response = _fallback_bootstrap(lang=lang, max_suggestions=request.max_suggestions)
            else:
                # Build a compact schema summary for the LLM.
                max_tables_in_prompt = min(12, len(tables))
                _logical, schema_summary = _schema_summary_from_tables(tables, max_tables=max_tables_in_prompt)
                
                # Contexto de permissões
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
                            # Validar sugestões (código existente)
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
                                filtered_count = 0
                                
                                for sug in suggestions:
                                    if sug.kind == "action":
                                        filtered_suggestions.append(sug)
                                        continue
                                    
                                    question_text = sug.question or ""
                                    if question_text:
                                        should_filter = suggestion_validator.should_filter_suggestion(question_text)
                                        if should_filter:
                                            filtered_count += 1
                                            continue
                                    
                                    filtered_suggestions.append(sug)
                                
                                suggestions = filtered_suggestions
                            except Exception:
                                pass  # Continuar sem validação se falhar
                            
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
        
        # Mostrar resultados
        print(f"\n✅ Greeting: {response.greeting[:100]}...")
        print(f"✅ Total de sugestões: {len(response.suggestions)}")
        print(f"✅ Meta: {json.dumps(response.meta, indent=2, default=str)}")
        
        print("\n📝 SUGESTÕES:")
        for i, sug in enumerate(response.suggestions, 1):
            if sug.kind == "action":
                print(f"  {i}. [AÇÃO] {sug.title}")
            else:
                print(f"  {i}. {sug.title}")
                print(f"     Pergunta: {sug.question}")
        
        return response
        
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
    print("🧪 TESTE DE BOOTSTRAP COM PERMISSÕES")
    print("="*80)
    print(f"Space ID: {TEST_SPACE_ID}")
    print(f"Connection ID: {TEST_CONNECTION_ID}")
    print()
    
    # Teste 1: Modo Personal
    print("\n" + "="*80)
    response_personal = test_bootstrap_mode(is_personal=True, mode_name="PERSONAL")
    
    # Teste 2: Modo Collaborative
    print("\n" + "="*80)
    response_collab = test_bootstrap_mode(is_personal=False, mode_name="COLLABORATIVE")
    
    # Comparação
    print("\n" + "="*80)
    print("📊 COMPARAÇÃO DOS MODOS")
    print("="*80)
    
    if response_personal and response_collab:
        personal_tables = response_personal.meta.get("num_tables", 0) if response_personal.meta else 0
        collab_tables = response_collab.meta.get("num_tables", 0) if response_collab.meta else 0
        
        print(f"Modo Personal: {personal_tables} tabelas")
        print(f"Modo Collaborative: {collab_tables} tabelas")
        print(f"Diferença: {personal_tables - collab_tables} tabelas")
        
        if personal_tables >= collab_tables:
            print("✅ Modo Personal tem acesso a mais ou igual número de tabelas (esperado)")
        else:
            print("⚠️  Modo Personal tem menos tabelas que Collaborative (inesperado)")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())


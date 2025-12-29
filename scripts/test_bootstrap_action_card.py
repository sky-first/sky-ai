#!/usr/bin/env python3
"""
Testa se o card "Create dashboard" está sempre presente nas sugestões do bootstrap.
"""

import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Adicionar raiz do projeto ao path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy.orm import Session
from db.session import SessionLocal
from api.routes.connection_query import chat_bootstrap
from api.schemas import ChatBootstrapRequest

# Configurações
TEST_CONNECTION_ID = os.getenv("TEST_CONNECTION_ID") or "1fd6fee8-bf03-4e82-9c85-419a228ef726"
TEST_SPACE_ID = os.getenv("TEST_SPACE_ID") or "e409079b-5bbf-4249-a769-2010609c30f2"
TEST_USER_ID = os.getenv("TEST_USER_ID") or "00000000-0000-0000-0000-000000000000"


async def test_action_card_presence():
    """Testa se o card de ação está sempre presente"""
    print("=" * 70)
    print("TESTE: Card 'Create dashboard' sempre presente")
    print("=" * 70)
    print()
    
    db = SessionLocal()
    
    try:
        # Primeira chamada (gera e cacheia)
        print("📞 TESTE 1: Primeira chamada (gera sugestões)")
        print("-" * 70)
        
        request1 = ChatBootstrapRequest(
            user_id=TEST_USER_ID,
            space_id=TEST_SPACE_ID,
            is_personal=True,
            language="en",
            max_suggestions=5,
        )
        
        response1 = await chat_bootstrap(TEST_CONNECTION_ID, request1, db)
        
        has_action_card_1 = any(
            sug.kind == "action" and sug.action_id == "create_dashboard"
            for sug in response1.suggestions
        )
        
        print(f"   ✅ Sugestões geradas: {len(response1.suggestions)}")
        print(f"   {'✅' if has_action_card_1 else '❌'} Card 'Create dashboard' presente: {has_action_card_1}")
        
        if has_action_card_1:
            action_card = next(
                (sug for sug in response1.suggestions if sug.kind == "action" and sug.action_id == "create_dashboard"),
                None
            )
            if action_card:
                print(f"   📋 Título do card: '{action_card.title}'")
                print(f"   🔑 Action ID: {action_card.action_id}")
        
        # Segunda chamada (deve vir do cache)
        print("\n📞 TESTE 2: Segunda chamada (deve vir do cache)")
        print("-" * 70)
        
        request2 = ChatBootstrapRequest(
            user_id=TEST_USER_ID,
            space_id=TEST_SPACE_ID,
            is_personal=True,
            language="en",
            max_suggestions=5,
        )
        
        response2 = await chat_bootstrap(TEST_CONNECTION_ID, request2, db)
        
        has_action_card_2 = any(
            sug.kind == "action" and sug.action_id == "create_dashboard"
            for sug in response2.suggestions
        )
        
        cached = response2.meta.get("cached", False) if response2.meta else False
        
        print(f"   💾 Veio do cache: {'SIM' if cached else 'NÃO'}")
        print(f"   ✅ Sugestões retornadas: {len(response2.suggestions)}")
        print(f"   {'✅' if has_action_card_2 else '❌'} Card 'Create dashboard' presente: {has_action_card_2}")
        
        if has_action_card_2:
            action_card = next(
                (sug for sug in response2.suggestions if sug.kind == "action" and sug.action_id == "create_dashboard"),
                None
            )
            if action_card:
                print(f"   📋 Título do card: '{action_card.title}'")
        
        # Verificar se está na primeira posição
        if response2.suggestions:
            first_suggestion = response2.suggestions[0]
            is_first = (
                first_suggestion.kind == "action" and 
                first_suggestion.action_id == "create_dashboard"
            )
            print(f"   {'✅' if is_first else '⚠️ '} Card está na primeira posição: {is_first}")
        
        print("\n" + "=" * 70)
        print("RESUMO")
        print("=" * 70)
        
        if has_action_card_1 and has_action_card_2:
            print("✅ SUCESSO: Card 'Create dashboard' está sempre presente!")
            print("   - Primeira chamada: ✅")
            print("   - Segunda chamada (cache): ✅")
            return True
        else:
            print("❌ FALHA: Card 'Create dashboard' não está presente em todas as chamadas")
            if not has_action_card_1:
                print("   - Primeira chamada: ❌")
            if not has_action_card_2:
                print("   - Segunda chamada: ❌")
            return False
            
    except Exception as e:
        print(f"\n❌ ERRO durante teste: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    success = asyncio.run(test_action_card_presence())
    sys.exit(0 if success else 1)


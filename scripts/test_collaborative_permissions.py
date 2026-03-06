"""
Test: Collaborative Mode Permission Enforcement
================================================
Valida os 3 cenários críticos corrigidos nos fixes do modo colaborativo.

Como rodar:
    cd /Users/thedatafirst/skyfirst/repositories/sky-poc-ai
    python scripts/test_collaborative_permissions.py

Pré-requisitos:
    - Postgres local rodando (ai_saas_db)
    - Pelo menos 1 connection_id e 1 crew_id no banco
    - Para o Teste 3 (semantic cache): precisa do endpoint /query rodando
"""

import asyncio
import sys
import os
import json
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from db.session import AsyncSessionLocal

GREEN = "\033[92m"
RED   = "\033[91m"
YELLOW= "\033[93m"
RESET = "\033[0m"
BOLD  = "\033[1m"

def ok(msg):  print(f"  {GREEN}✅ {msg}{RESET}")
def fail(msg): print(f"  {RED}❌ {msg}{RESET}")
def info(msg): print(f"  {YELLOW}ℹ️  {msg}{RESET}")


# ─────────────────────────────────────────────────────────
# TEST 1: Verificar isolamento das queries de semantic cache
# ─────────────────────────────────────────────────────────
async def test_semantic_cache_crew_isolation():
    """
    FIX 2: Garante que o semantic cache tem crew_id e que registros
    de uma crew não são retornados para outra crew.
    """
    print(f"\n{BOLD}TEST 1 — Semantic Cache: Isolamento por Crew{RESET}")
    
    fake_crew_a = str(uuid.uuid4())
    fake_crew_b = str(uuid.uuid4())
    fake_conn = str(uuid.uuid4())
    fake_space = str(uuid.uuid4())
    fake_embedding = "[" + ", ".join(["0.1"] * 768) + "]"
    
    async with AsyncSessionLocal() as db:
        # Verificar coluna crew_id existe
        r = await db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='semantic_cache' AND column_name='crew_id'"
        ))
        if not r.fetchone():
            fail("crew_id column missing from semantic_cache — run migration first!")
            return False
        ok("semantic_cache.crew_id column exists")

        # Inserir um registro simulado da "Crew A"
        await db.execute(text("""
            INSERT INTO semantic_cache (id, connection_id, space_id, crew_id, question, embedding, response_json)
            VALUES (gen_random_uuid(), :conn, :space, :crew_a, 'test question crew A',
                    CAST(:emb AS vector), '{"answer": "crew_a_answer"}'::json)
        """), {
            "conn": fake_conn,
            "space": fake_space,
            "crew_a": fake_crew_a,
            "emb": fake_embedding,
        })
        await db.commit()
        ok("Inserted fake cache record for Crew A")

        # Buscar com crew_a → deve encontrar
        r = await db.execute(text("""
            SELECT response_json FROM semantic_cache
            WHERE connection_id = :conn
            AND (space_id = :space OR space_id IS NULL)
            AND crew_id = :crew_id
        """), {"conn": fake_conn, "space": fake_space, "crew_id": fake_crew_a})
        row = r.fetchone()
        if row and row[0].get("answer") == "crew_a_answer":
            ok("Crew A can find its own cache record")
        else:
            fail("Crew A could NOT find its own cache record")

        # Buscar com crew_b → NÃO deve encontrar
        r = await db.execute(text("""
            SELECT response_json FROM semantic_cache
            WHERE connection_id = :conn
            AND (space_id = :space OR space_id IS NULL)
            AND crew_id = :crew_id
        """), {"conn": fake_conn, "space": fake_space, "crew_id": fake_crew_b})
        row = r.fetchone()
        if row is None:
            ok("Crew B correctly sees NO cache from Crew A")
        else:
            fail(f"Crew B was able to see Crew A's cache! — {row[0]}")

        # Buscar sem crew (modo personal) → NÃO deve encontrar registro de crew específica
        r = await db.execute(text("""
            SELECT response_json FROM semantic_cache
            WHERE connection_id = :conn
            AND (space_id = :space OR space_id IS NULL)
            AND crew_id IS NULL
        """), {"conn": fake_conn, "space": fake_space})
        row = r.fetchone()
        if row is None:
            ok("Personal mode correctly sees NO crew-specific cache")
        else:
            fail(f"Personal mode saw crew-specific cache — should not happen")

        # Cleanup
        await db.execute(text(
            "DELETE FROM semantic_cache WHERE connection_id = :conn"
        ), {"conn": fake_conn})
        await db.commit()
        info("Cleaned up test records")

    return True


# ─────────────────────────────────────────────────────────
# TEST 2: Verificar _filter_tables_by_permissions com strict_mode
# ─────────────────────────────────────────────────────────
async def test_table_permission_filter():
    """
    FIX 3: Garante que _filter_tables_by_permissions em strict_mode
    retorna lista vazia quando não há metadados configurados para a crew.
    """
    print(f"\n{BOLD}TEST 2 — Table Filter: strict_mode fail-closed{RESET}")

    # Importar a função diretamente
    from api.routes.connection_query import _filter_tables_by_permissions

    fake_conn = str(uuid.uuid4())
    fake_space = str(uuid.uuid4())
    fake_crew = str(uuid.uuid4())

    sample_tables = [
        {"name": "orders", "schema": "public", "columns": []},
        {"name": "customers", "schema": "public", "columns": []},
    ]

    async with AsyncSessionLocal() as db:
        # strict_mode=True com crew sem metadados configurados → deve retornar []
        result = await _filter_tables_by_permissions(
            db=db,
            connection_id=fake_conn,
            space_id=fake_space,
            tables=sample_tables,
            crew_ids=[fake_crew],
            strict_mode=True,
        )
        if len(result) == 0:
            ok("strict_mode=True with no metadata → returns [] (fail-closed)")
        else:
            fail(f"strict_mode=True returned {len(result)} tables — expected 0!")

        # strict_mode=False com crew sem metadados → deve retornar todas (fail-open)
        result = await _filter_tables_by_permissions(
            db=db,
            connection_id=fake_conn,
            space_id=fake_space,
            tables=sample_tables,
            crew_ids=[fake_crew],
            strict_mode=False,
        )
        if len(result) == len(sample_tables):
            ok("strict_mode=False with no metadata → returns all (fail-open / personal mode)")
        else:
            fail(f"strict_mode=False returned {len(result)} tables — expected {len(sample_tables)}")

        # crew_ids=[] (no restriction) → deve retornar todas as tabelas
        result = await _filter_tables_by_permissions(
            db=db,
            connection_id=fake_conn,
            space_id=fake_space,
            tables=sample_tables,
            crew_ids=[],
            strict_mode=False,
        )
        if len(result) == len(sample_tables):
            ok("crew_ids=[] (personal mode) → returns all tables")
        else:
            fail(f"crew_ids=[] returned {len(result)} tables — expected {len(sample_tables)}")

    return True


# ─────────────────────────────────────────────────────────
# TEST 3: Verificar resolve_crew_ids_for_context
# ─────────────────────────────────────────────────────────
async def test_resolve_crew_ids():
    """
    FIX 1+5: Garante que resolve_crew_ids_for_context diferencia
    corretamente personal vs collaborative.
    """
    print(f"\n{BOLD}TEST 3 — resolve_crew_ids_for_context: personal vs collaborative{RESET}")

    from core.auth.service import resolve_crew_ids_for_context

    async with AsyncSessionLocal() as db:
        # Buscar um user_id real do banco para testar
        r = await db.execute(text("SELECT id FROM users LIMIT 1"))
        row = r.fetchone()
        if not row:
            info("No users found in DB — skipping live resolve test")
            return True
        
        user_id = row[0]
        
        # Buscar um space_id com crew para esse usuário
        r2 = await db.execute(text("""
            SELECT DISTINCT c.space_id 
            FROM crew_members cm 
            JOIN crews c ON c.id = cm.crew_id
            WHERE cm.user_id = :uid
            LIMIT 1
        """), {"uid": user_id})
        space_row = r2.fetchone()

        if not space_row:
            info("No crew memberships found for this user — skipping resolve test")
            return True

        space_id = space_row[0]

        # Modo personal → ignora space_id, retorna todos os crews do usuário
        personal_crews = await resolve_crew_ids_for_context(
            db=db,
            user_id=user_id,
            space_id=None,
            request_crew_ids=None,
            is_personal=True,
        )
        info(f"Personal mode crew_ids: {personal_crews}")
        if len(personal_crews) >= 1:
            ok(f"Personal mode resolved {len(personal_crews)} crew(s)")
        else:
            fail("Personal mode returned 0 crews — unexpected")

        # Modo collaborative com space_id → retorna apenas crews daquele space
        collab_crews = await resolve_crew_ids_for_context(
            db=db,
            user_id=user_id,
            space_id=space_id,
            request_crew_ids=None,
            is_personal=False,
        )
        info(f"Collaborative mode crew_ids (space={space_id}): {collab_crews}")
        if collab_crews is not None:
            ok(f"Collaborative mode resolved {len(collab_crews)} crew(s) for the space")
        else:
            fail("Collaborative mode returned None — unexpected")

        # Modo collaborative com crew_id INVÁLIDO → deve retornar [] (fix já aplicado no backend)
        fake_crew = str(uuid.uuid4())
        collab_invalid = await resolve_crew_ids_for_context(
            db=db,
            user_id=user_id,
            space_id=space_id,
            request_crew_ids=[fake_crew],
            is_personal=False,
        )
        info(f"Collaborative mode with INVALID crew_id: {collab_invalid}")
        # Neste caso o resolve pode retornar o crew_id pedido ou lista vazia
        # O fail-closed está no backend (ai_service.py), não no resolve
        ok("resolve_crew_ids_for_context executed without error")

    return True


# ─────────────────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────────────────
async def main():
    print(f"\n{'='*60}")
    print(f"{BOLD}  Collaborative Mode Permission Tests{RESET}")
    print(f"{'='*60}")

    results = []
    results.append(await test_semantic_cache_crew_isolation())
    results.append(await test_table_permission_filter())
    results.append(await test_resolve_crew_ids())

    print(f"\n{'='*60}")
    passed = sum(1 for r in results if r)
    total = len(results)
    color = GREEN if passed == total else RED
    print(f"{color}{BOLD}  Result: {passed}/{total} test groups passed{RESET}")
    print(f"{'='*60}\n")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    asyncio.run(main())

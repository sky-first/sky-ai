#!/usr/bin/env python3
"""
RAG Phase 1 Setup Script

Prepares the RAG system for Ollama deployment by:
1. Running database migrations (multi-layer RAG tables)
2. Embedding existing table metadata
3. Populating business glossary
4. Populating metrics catalog
5. Validating RAG coverage

Usage:
    python scripts/setup_rag_phase1.py --space-id <space-uuid>
    python scripts/setup_rag_phase1.py --dry-run  # Test mode
"""
import sys
import os
import asyncio
from pathlib import Path
from typing import List, Dict
import argparse

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from config.settings import settings
from core.rag.embeddings import OpenAIEmbeddingProvider, create_embeddings_for_table_metadata
from core.logging_utils import log_event
from db.models import Base


# ============================================================================
# Step 1: Run Migrations
# ============================================================================

def run_migration(migration_file: str):
    """Run SQL migration file"""
    print(f"\n{'='*60}")
    print(f"📋 Step 1: Running Migration")
    print(f"{'='*60}")
    
    migration_path = project_root / migration_file
    if not migration_path.exists():
        print(f"❌ Migration file not found: {migration_path}")
        return False
    
    # Read migration SQL
    with open(migration_path, 'r') as f:
        sql_content = f.read()
    
    # Create sync engine for migration
    db_url = settings.database_url
    if db_url.startswith("postgresql+asyncpg://"):
        sync_db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    else:
        sync_db_url = db_url
    
    engine = create_engine(sync_db_url)
    
    try:
        print(f"🔌 Connecting to database...")
        with engine.connect() as conn:
            with conn.begin():
                # Split by semicolons and execute
                statements = [
                    stmt.strip() 
                    for stmt in sql_content.split(';') 
                    if stmt.strip() and not stmt.strip().startswith('--')
                ]
                
                for i, stmt in enumerate(statements, 1):
                    if stmt:
                        print(f"  Executing statement {i}/{len(statements)}...")
                        conn.execute(text(stmt))
        
        print(f"✅ Migration completed successfully!")
        print(f"📊 Tables created:")
        print(f"   - metrics_catalog")
        print(f"   - query_comments")
        print(f"   - business_glossary")
        print(f"   - query_history.question_embedding column")
        return True
        
    except Exception as e:
        # Check if error is "table already exists"
        if "already exists" in str(e).lower():
            print(f"⚠️  Tables already exist (migration was run before)")
            return True
        else:
            print(f"❌ Migration failed: {e}")
            return False
    finally:
        engine.dispose()


# ============================================================================
# Step 2: Embed Table Metadata
# ============================================================================

async def embed_table_metadata(space_id: str, connection_id: str = None):
    """Generate embeddings for existing table metadata"""
    print(f"\n{'='*60}")
    print(f"📦 Step 2: Embedding Table Metadata")
    print(f"{'='*60}")
    
    # Create async engine
    async_engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    
    try:
        embedding_provider = OpenAIEmbeddingProvider()
        
        async with async_session() as db:
            print(f"🧠 Generating embeddings (OpenAI text-embedding-3-large)...")
            
            num_embeddings = await create_embeddings_for_table_metadata(
                db=db,
                embedding_provider=embedding_provider,
                space_id=space_id,
                data_connection_id=connection_id,
                batch_size=20,  # Process 20 at a time
                delay_between_batches=1.0  # 1s delay to avoid rate limits
            )
            
            print(f"\n✅ Embedded {num_embeddings} table metadata records")
            return num_embeddings
            
    except Exception as e:
        print(f"❌ Embedding failed: {e}")
        import traceback
        traceback.print_exc()
        return 0
    finally:
        await async_engine.dispose()


# ============================================================================
# Step 3: Populate Business Glossary
# ============================================================================

def populate_glossary(space_id: str):
    """Populate business_glossary with common terms"""
    print(f"\n{'='*60}")
    print(f"📚 Step 3: Populating Business Glossary")
    print(f"{'='*60}")
    
    common_terms = [
        ("MRR", "Monthly Recurring Revenue", "subscription", "Sum of active subscription amounts per month"),
        ("ARR", "Annual Recurring Revenue", "subscription", "MRR × 12, total yearly recurring revenue"),
        ("Churn Rate", "Customer Churn", "retention", "Percentage of customers who cancelled in a period"),
        ("CAC", "Customer Acquisition Cost", "marketing", "Total marketing/sales spend divided by new customers acquired"),
        ("LTV", "Customer Lifetime Value", "revenue", "Average revenue per customer multiplied by average customer lifetime"),
        ("ARPU", "Average Revenue Per User", "revenue", "Total revenue divided by total number of users"),
        ("NPS", "Net Promoter Score", "satisfaction", "Customer satisfaction metric from -100 to +100"),
        ("ROI", "Return on Investment", "finance", "Net profit divided by investment cost, expressed as percentage"),
        ("KPI", "Key Performance Indicator", "metrics", "Measurable value demonstrating effectiveness of objectives"),
        ("SaaS", "Software as a Service", "business_model", "Cloud-based software delivery model with subscriptions"),
        ("Active User", "Active User", "engagement", "User who performed key action in defined time period"),
        ("Conversion Rate", "Conversion Rate", "marketing", "Percentage of visitors who complete desired action"),
        ("Gross Margin", "Gross Profit Margin", "finance", "(Revenue - COGS) / Revenue, expressed as percentage"),
        ("Burn Rate", "Cash Burn Rate", "finance", "Rate at which company spends cash reserves"),
        ("Runway", "Financial Runway", "finance", "Months of operation remaining at current burn rate"),
    ]
    
    # Create sync engine
    db_url = settings.database_url
    if db_url.startswith("postgresql+asyncpg://"):
        sync_db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    else:
        sync_db_url = db_url
    
    engine = create_engine(sync_db_url)
    
    try:
        with engine.connect() as conn:
            with conn.begin():
                inserted = 0
                for term, name, category, definition in common_terms:
                    try:
                        conn.execute(
                            text("""
                                INSERT INTO business_glossary (term, business_name, category, definition, space_id)
                                VALUES (:term, :name, :category, :definition, :space_id)
                                ON CONFLICT (space_id, term) DO NOTHING
                            """),
                            {
                                "term": term,
                                "name": name,
                                "category": category,
                                "definition": definition,
                                "space_id": space_id
                            }
                        )
                        inserted += 1
                        print(f"  ✅ {term}: {definition[:60]}...")
                    except Exception as e:
                        print(f"  ⚠️  Skipped {term}: {e}")
                
                print(f"\n✅ Inserted {inserted}/{len(common_terms)} glossary terms")
                return inserted
                
    except Exception as e:
        print(f"❌ Failed to populate glossary: {e}")
        return 0
    finally:
        engine.dispose()


# ============================================================================
# Step 4: Populate Metrics Catalog
# ============================================================================

def populate_metrics(space_id: str):
    """Populate metrics_catalog with common KPIs"""
    print(f"\n{'='*60}")
    print(f"📊 Step 4: Populating Metrics Catalog")
    print(f"{'='*60}")
    
    common_metrics = [
        ("MRR", "Monthly Recurring Revenue", "SUM(amount) WHERE subscription_status = 'active'", "Revenue"),
        ("ARR", "Annual Recurring Revenue", "SUM(amount) * 12 WHERE subscription_status = 'active'", "Revenue"),
        ("Total Customers", "Active Customer Count", "COUNT(DISTINCT customer_id) WHERE status = 'active'", "Customers"),
        ("New Customers", "New Customers This Month", "COUNT(DISTINCT customer_id) WHERE created_at >= DATE_TRUNC('month', CURRENT_DATE)", "Customers"),
        ("Churn Rate", "Monthly Churn Rate", "(COUNT cancelled / COUNT total) * 100", "Retention"),
        ("Average Order Value", "AOV", "SUM(amount) / COUNT(DISTINCT invoice_id)", "Revenue"),
        ("Revenue Growth", "MoM Revenue Growth", "((current_month - previous_month) / previous_month) * 100", "Growth"),
        ("Active Subscriptions", "Active Subscription Count", "COUNT(*) FROM subscriptions WHERE status = 'active'", "Subscriptions"),
    ]
    
    # Create sync engine
    db_url = settings.database_url
    if db_url.startswith("postgresql+asyncpg://"):
        sync_db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    else:
        sync_db_url = db_url
    
    engine = create_engine(sync_db_url)
    
    try:
        with engine.connect() as conn:
            with conn.begin():
                inserted = 0
                for name, desc, calc, category in common_metrics:
                    try:
                        conn.execute(
                            text("""
                                INSERT INTO metrics_catalog (metric_name, description, calculation_sql, category, space_id)
                                VALUES (:name, :desc, :calc, :category, :space_id)
                                ON CONFLICT (space_id, metric_name) DO NOTHING
                            """),
                            {
                                "name": name,
                                "desc": desc,
                                "calc": calc,
                                "category": category,
                                "space_id": space_id
                            }
                        )
                        inserted += 1
                        print(f"  ✅ {name}: {desc}")
                    except Exception as e:
                        print(f"  ⚠️  Skipped {name}: {e}")
                
                print(f"\n✅ Inserted {inserted}/{len(common_metrics)} metrics")
                return inserted
                
    except Exception as e:
        print(f"❌ Failed to populate metrics: {e}")
        return 0
    finally:
        engine.dispose()


# ============================================================================
# Step 5: Validation
# ============================================================================

def validate_setup(space_id: str):
    """Validate RAG setup"""
    print(f"\n{'='*60}")
    print(f"🔍 Step 5: Validating Setup")
    print(f"{'='*60}")
    
    # Create sync engine
    db_url = settings.database_url
    if db_url.startswith("postgresql+asyncpg://"):
        sync_db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    else:
        sync_db_url = db_url
    
    engine = create_engine(sync_db_url)
    
    try:
        with engine.connect() as conn:
            # Check embeddings
            result = conn.execute(
                text("SELECT COUNT(*) FROM embeddings WHERE space_id = :space_id"),
                {"space_id": space_id}
            )
            embeddings_count = result.scalar()
            
            # Check glossary
            result = conn.execute(
                text("SELECT COUNT(*) FROM business_glossary WHERE space_id = :space_id"),
                {"space_id": space_id}
            )
            glossary_count = result.scalar()
            
            # Check metrics
            result = conn.execute(
                text("SELECT COUNT(*) FROM metrics_catalog WHERE space_id = :space_id"),
                {"space_id": space_id}
            )
            metrics_count = result.scalar()
            
            print(f"\n📊 Validation Results:")
            print(f"   Embeddings: {embeddings_count} {'✅' if embeddings_count > 0 else '❌'}")
            print(f"   Glossary Terms: {glossary_count} {'✅' if glossary_count >= 10 else '⚠️'}")
            print(f"   Metrics: {metrics_count} {'✅' if metrics_count >= 5 else '⚠️'}")
            
            # Overall assessment
            if embeddings_count > 0 and glossary_count >= 10 and metrics_count >= 5:
                print(f"\n🎉 Phase 1 COMPLETE! RAG is ready for Ollama.")
                print(f"\n💡 Expected RAG chunks per query: 8-12")
                print(f"   - Schema RAG: 3 chunks (from embeddings)")
                print(f"   - Metrics RAG: 2-3 chunks (from catalog)")
                print(f"   - Glossary RAG: 1-2 chunks (from glossary)")
                print(f"   - Questions RAG: 0-2 chunks (will improve over time)")
                return True
            else:
                print(f"\n⚠️  Phase 1 incomplete. Some components missing.")
                return False
                
    except Exception as e:
        print(f"❌ Validation failed: {e}")
        return False
    finally:
        engine.dispose()


# ============================================================================
# Main
# ============================================================================

async def main():
    parser = argparse.ArgumentParser(description="RAG Phase 1 Setup")
    parser.add_argument("--space-id", help="Space UUID to setup RAG for")
    parser.add_argument("--connection-id", help="Data connection UUID (optional)")
    parser.add_argument("--dry-run", action="store_true", help="Test mode (no changes)")
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"🚀 RAG Phase 1 Setup - Preparing for Ollama")
    print(f"{'='*60}")
    
    if args.dry_run:
        print(f"🧪 DRY RUN MODE - No changes will be made")
        print(f"\nThis script will:")
        print(f"  1. Run migration (create RAG tables)")
        print(f"  2. Embed table metadata (OpenAI)")
        print(f"  3. Populate business glossary (15 terms)")
        print(f"  4. Populate metrics catalog (8 metrics)")
        print(f"  5. Validate setup")
        return
    
    if not args.space_id:
        print(f"❌ Error: --space-id is required")
        print(f"\nUsage:")
        print(f"  python scripts/setup_rag_phase1.py --space-id <uuid>")
        print(f"  python scripts/setup_rag_phase1.py --dry-run")
        sys.exit(1)
    
    print(f"📍 Space ID: {args.space_id}")
    if args.connection_id:
        print(f"📍 Connection ID: {args.connection_id}")
    
    # Step 1: Migration
    migration_ok = run_migration("db/migrations/add_multi_layer_rag_tables.sql")
    if not migration_ok:
        print(f"\n❌ Migration failed. Aborting.")
        sys.exit(1)
    
    # Step 2: Embed metadata
    num_embeddings = await embed_table_metadata(args.space_id, args.connection_id)
    
    # Step 3: Populate glossary
    num_glossary = populate_glossary(args.space_id)
    
    # Step 4: Populate metrics
    num_metrics = populate_metrics(args.space_id)
    
    # Step 5: Validate
    success = validate_setup(args.space_id)
    
    if success:
        print(f"\n{'='*60}")
        print(f"✅ RAG Phase 1 Setup Complete!")
        print(f"{'='*60}")
        print(f"\nNext Steps:")
        print(f"  1. Test RAG: Make a query and check logs for 'multi_layer_rag_retrieved'")
        print(f"  2. Deploy Ollama: Get API endpoint from DevOps")
        print(f"  3. Switch models: python scripts/switch_to_ollama.py --enable")
        sys.exit(0)
    else:
        print(f"\n⚠️  Setup incomplete. Review errors above.")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

-- Database migrations for Multi-Layer RAG support
-- 
-- Adds 3 new tables to support advanced RAG retrieval:
-- 1. metrics_catalog - Business KPI definitions
-- 2. query_comments - User clarifications and corrections
-- 3. business_glossary - Domain terminology
-- 
-- Run this migration to enable full multi-layer RAG functionality.

-- ============================================================================
-- Table 1: metrics_catalog
-- Business metric definitions with embeddings
-- ============================================================================

CREATE TABLE IF NOT EXISTS metrics_catalog (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    space_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Metric details
    metric_name TEXT NOT NULL,
    definition TEXT NOT NULL,
    calculation_sql TEXT,
    business_owner TEXT,
    category TEXT,  -- e.g., 'revenue', 'churn', 'growth'
    
    -- Embedding for semantic search
    metric_embedding VECTOR(768),  -- Ollama nomic-embed-text dimension (768)
    
    -- Indexes
    CONSTRAINT metrics_catalog_space_metric_unique UNIQUE (space_id, metric_name)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_metrics_catalog_space_id 
ON metrics_catalog (space_id);

CREATE INDEX IF NOT EXISTS idx_metrics_catalog_embedding 
ON metrics_catalog USING ivfflat (metric_embedding vector_cosine_ops)
WITH (lists = 100);

COMMENT ON TABLE metrics_catalog IS 'Business metric definitions for RAG retrieval';
COMMENT ON COLUMN metrics_catalog.metric_embedding IS 'Embedding of metric_name + definition for semantic search';

-- ============================================================================
-- Table 2: query_comments
-- User clarifications and corrections
-- ============================================================================

CREATE TABLE IF NOT EXISTS query_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    space_id UUID NOT NULL,
    user_id UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Comment details
    original_question TEXT NOT NULL,
    comment_text TEXT NOT NULL,
    correction_type TEXT,  -- e.g., 'column_usage', 'business_logic', 'filter_clarification'
    
    -- Link to original query (optional)
    related_query_id UUID,
    
    -- Embedding for semantic search
    comment_embedding VECTOR(768),
    
    -- Indexes
    CONSTRAINT query_comments_space_question_unique UNIQUE (space_id, original_question, comment_text)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_query_comments_space_id 
ON query_comments (space_id);

CREATE INDEX IF NOT EXISTS idx_query_comments_embedding 
ON query_comments USING ivfflat (comment_embedding vector_cosine_ops)
WITH (lists = 100);

COMMENT ON TABLE query_comments IS 'User comments and clarifications for RAG retrieval';
COMMENT ON COLUMN query_comments.comment_embedding IS 'Embedding of original_question + comment_text for semantic search';

-- ============================================================================
-- Table 3: business_glossary
-- Domain-specific terminology
-- ============================================================================

CREATE TABLE IF NOT EXISTS business_glossary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    space_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Term details
    term TEXT NOT NULL,  -- e.g., 'MRR', 'CAC', 'LTV'
    definition TEXT NOT NULL,
    category TEXT,  -- e.g., 'finance', 'marketing', 'product'
    synonyms TEXT[],  -- Alternative terms
    
    -- Embedding for semantic search
    term_embedding VECTOR(768),
    
    -- Indexes
    CONSTRAINT business_glossary_space_term_unique UNIQUE (space_id, term)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_business_glossary_space_id 
ON business_glossary (space_id);

CREATE INDEX IF NOT EXISTS idx_business_glossary_term 
ON business_glossary (space_id, term);

CREATE INDEX IF NOT EXISTS idx_business_glossary_embedding 
ON business_glossary USING ivfflat (term_embedding vector_cosine_ops)
WITH (lists = 100);

COMMENT ON TABLE business_glossary IS 'Business terminology and acronyms for RAG retrieval';
COMMENT ON COLUMN business_glossary.term_embedding IS 'Embedding of term + definition for semantic search';

-- ============================================================================
-- Optional: Add embedding column to existing query_history table
-- (Only if it doesn't exist yet)
-- ============================================================================

/*
DO $$
BEGIN
    -- Check if question_embedding column exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'query_history' 
        AND column_name = 'question_embedding'
    ) THEN
        -- Add embedding column
        ALTER TABLE query_history 
        ADD COLUMN question_embedding VECTOR(768);
        
        -- Add index
        CREATE INDEX idx_query_history_question_embedding 
        ON query_history USING ivfflat (question_embedding vector_cosine_ops)
        WITH (lists = 100);
        
        RAISE NOTICE 'Added question_embedding column to query_history';
    ELSE
        RAISE NOTICE 'question_embedding column already exists in query_history';
    END IF;
END $$;
*/

-- ============================================================================
-- Sample Data (Optional)
-- Populate with common business metrics and terminology
-- ============================================================================

-- Insert common SaaS metrics (embeddings will be generated by application)
INSERT INTO metrics_catalog (space_id, metric_name, definition, calculation_sql, category)
VALUES
    (
        (SELECT id FROM spaces LIMIT 1),  -- Use first available space
        'MRR',
        'Monthly Recurring Revenue: Sum of all active subscription amounts per month',
        'SELECT SUM(subscription_amount) FROM subscriptions WHERE status = ''active''',
        'revenue'
    ),
    (
        (SELECT id FROM spaces LIMIT 1),
        'Churn Rate',
        'Percentage of customers who cancelled in a given period',
        'SELECT (COUNT(*) FILTER (WHERE status = ''cancelled'') / COUNT(*)::float * 100) FROM customers',
        'retention'
    )
ON CONFLICT (space_id, metric_name) DO NOTHING;

-- Insert common business terms
INSERT INTO business_glossary (space_id, term, definition, category, synonyms)
VALUES
    (
        (SELECT id FROM spaces LIMIT 1),
        'MRR',
        'Monthly Recurring Revenue (subscription-based businesses)',
        'finance',
        ARRAY['Monthly Revenue', 'Recurring Revenue']
    ),
    (
        (SELECT id FROM spaces LIMIT 1),
        'CAC',
        'Customer Acquisition Cost: Total marketing and sales spend divided by new customers',
        'marketing',
        ARRAY['Acquisition Cost']
    ),
    (
        (SELECT id FROM spaces LIMIT 1),
        'LTV',
        'Lifetime Value: Expected total revenue from a customer over their lifetime',
        'finance',
        ARRAY['CLV', 'Customer Lifetime Value']
    )
ON CONFLICT (space_id, term) DO NOTHING;

-- ============================================================================
-- Migration Complete
-- ============================================================================

-- Verify tables were created
DO $$
DECLARE
    table_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO table_count
    FROM information_schema.tables
    WHERE table_name IN ('metrics_catalog', 'query_comments', 'business_glossary');
    
    RAISE NOTICE 'Multi-layer RAG migration complete. Tables created: %', table_count;
END $$;

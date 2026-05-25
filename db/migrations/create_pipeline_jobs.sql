-- Create pipeline_jobs table
CREATE TABLE IF NOT EXISTS pipeline_jobs (
    id VARCHAR PRIMARY KEY,
    status VARCHAR NOT NULL DEFAULT 'pending',
    result JSONB,
    error TEXT,
    user_id UUID REFERENCES users(id),
    connection_id UUID REFERENCES data_connections(id),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc')
);

CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_user_id ON pipeline_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_status ON pipeline_jobs(status);

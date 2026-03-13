-- 📦 Schema de Mapeamento Multi-tenant (SaaS Industry Standard)
-- Esta tabela permite que o sistema identifique qual cliente pertence a qual Organização Auth0.

CREATE TABLE IF NOT EXISTS public.tenant_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug VARCHAR(50) UNIQUE NOT NULL,       -- ex: 'teamblue-stg', 'bbombom-stg'
    auth0_org_id VARCHAR(100) UNIQUE NOT NULL, -- ex: 'org_CyKo...', 'org_XYZ...'
    db_name VARCHAR(50) UNIQUE NOT NULL,      -- ex: 'db_teamblue_stg', 'db_bbombom'
    company_name VARCHAR(100) NOT NULL,
    environment VARCHAR(20) DEFAULT 'staging',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- 📝 Inserir os dados dos seus 3 ambientes/clientes
INSERT INTO public.tenant_mappings (slug, auth0_org_id, db_name, company_name, environment)
VALUES 
('teamblue-stg', 'org_CyKoLUUWgvdVXRph', 'db_teamblue_stg', 'TeamBlue Corporation', 'staging'),
('staging',       'org_SkyInternalStg',  'db_sky_internal',  'Sky Platform Internal', 'staging'),
('workspace-stg', 'org_Wta5SKQarsjLgx31', 'db_sky_workspace', 'Sky Workspace Test',   'staging'),
('workspace-prd', 'org_SkyWorkspacePrd', 'db_sky_workspace_prd', 'Sky Workspace Production', 'production')
ON CONFLICT (slug) DO UPDATE SET auth0_org_id = EXCLUDED.auth0_org_id;

-- 💡 Dica: Quando entrar a Bbombom, você só roda um INSERT novo nesta tabela.

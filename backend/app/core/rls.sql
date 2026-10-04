-- Row Level Security for Supabase/Postgres (SECURITY.md §1, §4 of DATA-MODEL.md).
--
-- Applied by the Alembic migration on Postgres only. Application queries are
-- already scoped by owner_id; RLS is defense in depth and is the reason a leaked
-- service-role-less path still cannot read another creator's rows.
--
-- Convention:
--   * tables carrying owner_id directly  -> policy compares owner_id
--   * child tables without owner_id      -> policy joins to the parent
-- The generated models denormalise owner_id onto high-volume child tables
-- (scenes, transcript_segments, content_*, impact_*) so the policy is a cheap
-- column compare rather than a join.

-- --- Tables with a direct owner_id -----------------------------------------
DO $$
DECLARE
    t TEXT;
    owner_tables TEXT[] := ARRAY[
        'profiles', 'creator_dna', 'projects', 'creation_intents', 'assets',
        'scripts', 'hooks', 'references', 'shot_plans', 'clips', 'edits',
        'platform_variants', 'publishing_jobs', 'analytics', 'content_nodes',
        'content_edges', 'impact_events', 'impact_items', 'content_opportunities',
        'jobs', 'skill_runs', 'script_footage_matches'
    ];
BEGIN
    FOREACH t IN ARRAY owner_tables LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS %I ON %I', t || '_owner_isolation', t);
        -- profiles keys on auth.uid() itself, so it compares id.
        IF t = 'profiles' THEN
            EXECUTE format(
                'CREATE POLICY %I ON %I USING (id = auth.uid()) WITH CHECK (id = auth.uid())',
                t || '_owner_isolation', t);
        ELSE
            EXECUTE format(
                'CREATE POLICY %I ON %I USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid())',
                t || '_owner_isolation', t);
        END IF;
    END LOOP;
END $$;

-- --- Child tables reached through a parent --------------------------------
ALTER TABLE creation_blueprints ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS blueprints_owner_isolation ON creation_blueprints;
CREATE POLICY blueprints_owner_isolation ON creation_blueprints
    USING (EXISTS (SELECT 1 FROM projects p WHERE p.id = project_id AND p.owner_id = auth.uid()))
    WITH CHECK (EXISTS (SELECT 1 FROM projects p WHERE p.id = project_id AND p.owner_id = auth.uid()));

ALTER TABLE workflows ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS workflows_owner_isolation ON workflows;
CREATE POLICY workflows_owner_isolation ON workflows
    USING (EXISTS (SELECT 1 FROM projects p WHERE p.id = project_id AND p.owner_id = auth.uid()))
    WITH CHECK (EXISTS (SELECT 1 FROM projects p WHERE p.id = project_id AND p.owner_id = auth.uid()));

ALTER TABLE workflow_steps ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS workflow_steps_owner_isolation ON workflow_steps;
CREATE POLICY workflow_steps_owner_isolation ON workflow_steps
    USING (EXISTS (
        SELECT 1 FROM workflows w JOIN projects p ON p.id = w.project_id
        WHERE w.id = workflow_id AND p.owner_id = auth.uid()
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM workflows w JOIN projects p ON p.id = w.project_id
        WHERE w.id = workflow_id AND p.owner_id = auth.uid()
    ));

ALTER TABLE script_versions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS script_versions_owner_isolation ON script_versions;
CREATE POLICY script_versions_owner_isolation ON script_versions
    USING (EXISTS (SELECT 1 FROM scripts s WHERE s.id = script_id AND s.owner_id = auth.uid()))
    WITH CHECK (EXISTS (SELECT 1 FROM scripts s WHERE s.id = script_id AND s.owner_id = auth.uid()));

ALTER TABLE video_analyses ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS video_analyses_owner_isolation ON video_analyses;
CREATE POLICY video_analyses_owner_isolation ON video_analyses
    USING (EXISTS (SELECT 1 FROM assets a WHERE a.id = asset_id AND a.owner_id = auth.uid()))
    WITH CHECK (EXISTS (SELECT 1 FROM assets a WHERE a.id = asset_id AND a.owner_id = auth.uid()));

ALTER TABLE reference_dna ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS reference_dna_owner_isolation ON reference_dna;
CREATE POLICY reference_dna_owner_isolation ON reference_dna
    USING (EXISTS (SELECT 1 FROM references r WHERE r.id = reference_id AND r.owner_id = auth.uid()))
    WITH CHECK (EXISTS (SELECT 1 FROM references r WHERE r.id = reference_id AND r.owner_id = auth.uid()));

-- --- Vector index -----------------------------------------------------------
-- pgvector HNSW over cosine distance (DATA-MODEL.md §4). Created in the same
-- migration; guarded so the SQL is inert when the extension is unavailable.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
        CREATE EXTENSION IF NOT EXISTS vector;
        EXECUTE 'CREATE INDEX IF NOT EXISTS ix_asset_embeddings_hnsw
                 ON asset_embeddings USING hnsw (embedding vector_cosine_ops)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS ix_transcript_segments_hnsw
                 ON transcript_segments USING hnsw (embedding vector_cosine_ops)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS ix_scenes_hnsw
                 ON scenes USING hnsw (embedding vector_cosine_ops)';
    END IF;
END $$;

-- --- Storage policies (SECURITY.md §2) -------------------------------------
-- Buckets are private; objects live under {user_id}/...
INSERT INTO storage.buckets (id, name, public)
VALUES ('assets-original', 'assets-original', false),
       ('assets-derived', 'assets-derived', false),
       ('renders', 'renders', false)
ON CONFLICT (id) DO NOTHING;

DROP POLICY IF EXISTS storage_read_own ON storage.objects;
CREATE POLICY storage_read_own ON storage.objects
    FOR SELECT USING (bucket_id IN ('assets-original', 'assets-derived', 'renders')
                      AND (storage.foldername(name))[1] = auth.uid()::text);

DROP POLICY IF EXISTS storage_write_own ON storage.objects;
CREATE POLICY storage_write_own ON storage.objects
    FOR INSERT WITH CHECK (bucket_id IN ('assets-original', 'assets-derived', 'renders')
                           AND (storage.foldername(name))[1] = auth.uid()::text);

DROP POLICY IF EXISTS storage_delete_own ON storage.objects;
CREATE POLICY storage_delete_own ON storage.objects
    FOR DELETE USING (bucket_id IN ('assets-original', 'assets-derived', 'renders')
                      AND (storage.foldername(name))[1] = auth.uid()::text);
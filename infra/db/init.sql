-- Docker postgres first-boot: extensions only. Full schema is applied by Alembic
-- (`z0a1b2c3d4e5_initial_baseline` reads `infra/db/baseline_schema.sql`).
-- Keeps `docker compose up` + `make migrate` the single path for a new database.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

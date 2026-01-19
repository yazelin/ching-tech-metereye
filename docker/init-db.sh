#!/bin/bash
set -e

# Create read-only user for external access
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create read-only user
    CREATE USER ${READONLY_USER} WITH PASSWORD '${READONLY_PASSWORD}';

    -- Grant connect to database
    GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${READONLY_USER};

    -- Grant usage on schema
    GRANT USAGE ON SCHEMA public TO ${READONLY_USER};

    -- Grant SELECT on all existing tables
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${READONLY_USER};

    -- Grant SELECT on all future tables (for when app creates tables)
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO ${READONLY_USER};

    -- Also grant SELECT on sequences for completeness
    GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO ${READONLY_USER};
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO ${READONLY_USER};
EOSQL

echo "Read-only user '${READONLY_USER}' created successfully"

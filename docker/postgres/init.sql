-- PayLap PostgreSQL Initial Role and Database Setup

-- 1. Create Roles
DO
$do$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'paylap_owner') THEN
      CREATE ROLE paylap_owner WITH LOGIN PASSWORD 'paylap_owner_pass' SUPERUSER CREATEDB;
   END IF;
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'paylap_app') THEN
      CREATE ROLE paylap_app WITH LOGIN PASSWORD 'paylap_app_pass' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
   END IF;
END
$do$;

-- 2. Create Databases
SELECT 'CREATE DATABASE paylap OWNER paylap_owner'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'paylap')\gexec

SELECT 'CREATE DATABASE paylap_test OWNER paylap_owner'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'paylap_test')\gexec

-- 3. Configure paylap DB permissions
\c paylap

GRANT ALL ON SCHEMA public TO paylap_owner;
GRANT USAGE ON SCHEMA public TO paylap_app;
ALTER DEFAULT PRIVILEGES FOR ROLE paylap_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO paylap_app;
ALTER DEFAULT PRIVILEGES FOR ROLE paylap_owner IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO paylap_app;

-- 4. Configure paylap_test DB permissions
\c paylap_test

GRANT ALL ON SCHEMA public TO paylap_owner;
GRANT USAGE ON SCHEMA public TO paylap_app;
ALTER DEFAULT PRIVILEGES FOR ROLE paylap_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO paylap_app;
ALTER DEFAULT PRIVILEGES FOR ROLE paylap_owner IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO paylap_app;

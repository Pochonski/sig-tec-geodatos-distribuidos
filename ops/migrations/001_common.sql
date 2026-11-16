-- Ejecutar como administrador dentro de una transacción.
CREATE SCHEMA IF NOT EXISTS ops;
REVOKE ALL ON SCHEMA ops FROM PUBLIC;

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sig_tec_ops_cli') THEN
        CREATE ROLE sig_tec_ops_cli LOGIN;
    END IF;
    IF EXISTS (
        SELECT FROM pg_auth_members
        WHERE member = (SELECT oid FROM pg_roles WHERE rolname = 'sig_tec_ops_cli')
    ) THEN
        RAISE EXCEPTION 'sig_tec_ops_cli no debe pertenecer a otros roles';
    END IF;
END
$$;
ALTER ROLE sig_tec_ops_cli WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE sig_tec_ops_cli SET search_path = pg_catalog;
ALTER ROLE sig_tec_ops_cli SET synchronous_commit = on;
GRANT CONNECT ON DATABASE sig_tec TO sig_tec_ops_cli;
GRANT USAGE ON SCHEMA ops TO sig_tec_ops_cli;

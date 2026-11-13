CREATE SCHEMA IF NOT EXISTS cartago;
CREATE TABLE IF NOT EXISTS cartago.edificios (
    id bigint PRIMARY KEY,
    campus_id smallint NOT NULL CHECK (campus_id = 1),
    nombre text NOT NULL
);

CREATE TABLE IF NOT EXISTS ops.applied_operations (
    operation_id uuid PRIMARY KEY,
    campus_id smallint NOT NULL CHECK (campus_id = 1),
    building_id bigint NOT NULL,
    new_name text NOT NULL CHECK (length(btrim(new_name)) > 0),
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

REVOKE ALL ON ops.applied_operations FROM PUBLIC, sig_tec_ops_cli;
GRANT SELECT ON ops.applied_operations TO sig_tec_ops_cli;
GRANT INSERT (operation_id, campus_id, building_id, new_name)
    ON ops.applied_operations TO sig_tec_ops_cli;
GRANT USAGE ON SCHEMA cartago TO sig_tec_ops_cli;
REVOKE ALL ON cartago.edificios FROM sig_tec_ops_cli;
GRANT SELECT (id, campus_id, nombre), UPDATE (nombre)
    ON cartago.edificios TO sig_tec_ops_cli;

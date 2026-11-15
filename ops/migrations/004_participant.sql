-- El esquema geográfico debe existir antes de integrar un participante.
CREATE TABLE IF NOT EXISTS ops.applied_operations (
    operation_id uuid PRIMARY KEY,
    campus_id smallint NOT NULL CHECK (campus_id = :campus_id),
    building_id bigint NOT NULL,
    new_name text NOT NULL CHECK (length(btrim(new_name)) > 0),
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
REVOKE ALL ON ops.applied_operations FROM PUBLIC, sig_tec_ops_cli;
GRANT SELECT ON ops.applied_operations TO sig_tec_ops_cli;
GRANT INSERT (operation_id,campus_id,building_id,new_name) ON ops.applied_operations TO sig_tec_ops_cli;
GRANT USAGE ON SCHEMA :campus_schema TO sig_tec_ops_cli;
REVOKE ALL ON :campus_schema.edificios FROM sig_tec_ops_cli;
GRANT SELECT (id,campus_id,nombre), UPDATE (nombre) ON :campus_schema.edificios TO sig_tec_ops_cli;

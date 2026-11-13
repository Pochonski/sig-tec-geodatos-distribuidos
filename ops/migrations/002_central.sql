CREATE TABLE IF NOT EXISTS ops.requests (
    operation_id uuid PRIMARY KEY,
    campus_id smallint NOT NULL CHECK (campus_id BETWEEN 1 AND 5),
    building_id bigint NOT NULL,
    new_name text NOT NULL CHECK (length(btrim(new_name)) > 0),
    requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (operation_id, campus_id, building_id, new_name)
);

-- Una decisión por UUID. La CLI no puede cambiarla ni eliminarla.
CREATE TABLE IF NOT EXISTS ops.decisions (
    operation_id uuid PRIMARY KEY REFERENCES ops.requests (operation_id),
    decision text NOT NULL CHECK (decision IN ('COMMIT', 'ABORT')),
    decided_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Su existencia es el marcador aplicado del participante central.
CREATE TABLE IF NOT EXISTS ops.audit (
    operation_id uuid PRIMARY KEY,
    campus_id smallint NOT NULL,
    building_id bigint NOT NULL,
    new_name text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (operation_id, campus_id, building_id, new_name)
        REFERENCES ops.requests (operation_id, campus_id, building_id, new_name)
);

REVOKE ALL ON ops.requests, ops.decisions, ops.audit FROM PUBLIC, sig_tec_ops_cli;
GRANT SELECT ON ops.requests, ops.decisions, ops.audit TO sig_tec_ops_cli;
GRANT INSERT (operation_id, campus_id, building_id, new_name)
    ON ops.requests, ops.audit TO sig_tec_ops_cli;
GRANT INSERT (operation_id, decision) ON ops.decisions TO sig_tec_ops_cli;

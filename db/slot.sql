\set ON_ERROR_STOP on

SELECT pg_create_logical_replication_slot(:'slot_name', 'pgoutput')
WHERE NOT EXISTS (
    SELECT 1 FROM pg_replication_slots WHERE slot_name = :'slot_name'
);

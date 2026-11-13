-- Solo para el entorno aislado mínimo; no usar como semilla de integración.
INSERT INTO cartago.edificios (id, campus_id, nombre)
VALUES (1, 1, 'Edificio ficticio de operaciones - Cartago')
ON CONFLICT (id) DO NOTHING;

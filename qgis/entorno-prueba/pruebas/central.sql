-- Prueba de auth.mi_campus() con la cuenta conectada.
-- Uso: psql -v campus_esperado=1 ... (vacío para una cuenta sin asignación).
\set ON_ERROR_STOP on

SELECT session_user AS usuario, auth.mi_campus() AS campus_id;
SELECT auth.mi_campus() IS NOT DISTINCT FROM nullif(:'campus_esperado', '')::smallint AS correcto \gset
\if :correcto
  \echo 'ok: auth.mi_campus() devuelve el campus esperado'
\else
  \echo 'FALLO: auth.mi_campus() no devuelve el campus esperado'
  \quit 3
\endif

DO $$
BEGIN
  PERFORM count(*) FROM auth.asignaciones;
  RAISE EXCEPTION 'FALLO: la cuenta puede leer auth.asignaciones';
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'ok: la cuenta no puede leer el registro de asignaciones';
END
$$;

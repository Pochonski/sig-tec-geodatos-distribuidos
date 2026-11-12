#!/bin/sh
# Inicializa un campus simulado: ocho capas, vistas editables y suscripción a los estilos del central.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v campus_id="$CAMPUS_ID" \
  -v usuario_prueba="$USUARIO_PRUEBA" \
  -v clave_prueba="$CLAVE_PRUEBA" \
  -v suscripcion="estilos_campus_$CAMPUS_ID" \
  -v conexion_central="host=central port=5432 dbname=sig_tec user=replicador password=$CLAVE_REPLICADOR" \
  -f /sig-sql/campus.sql

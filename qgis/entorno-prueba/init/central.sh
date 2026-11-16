#!/bin/sh
# Inicializa el central simulado: cuentas, auth.mi_campus() y publicación de estilos.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v clave_prueba="$CLAVE_PRUEBA" \
  -v clave_replicador="$CLAVE_REPLICADOR" \
  -f /sig-sql/central.sql

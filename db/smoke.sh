#!/usr/bin/env bash
set -Eeuo pipefail

query() {
    local node="$1" user="$2" password="$3" sql="$4"
    PGPASSWORD="$password" psql -X -q -w -At -v ON_ERROR_STOP=1 \
        -h "$node" -U "$user" -d sig_tec -c "$sql"
}

require_equal() {
    if [[ "$1" != "$2" ]]; then
        echo "Se esperaba '$2' y se obtuvo '$1': $3" >&2
        exit 1
    fi
}

require_rejected() {
    local result
    if result=$(query "$@" 2>&1); then
        echo "Una escritura prohibida fue aceptada: $4" >&2
        exit 1
    fi
    if [[ "$result" != *"permission denied"* && "$result" != *"Solo puede"* && "$result" != *"inmutables"* ]]; then
        echo "La operación falló por un motivo inesperado: $result" >&2
        exit 1
    fi
}

wait_for() {
    local node="$1" user="$2" password="$3" sql="$4" expected="$5"
    local result
    for (( attempt = 0; attempt < 30; attempt++ )); do
        result=$(query "$node" "$user" "$password" "$sql")
        if [[ "$result" == "$expected" ]]; then
            return
        fi
        sleep 1
    done
    echo "No convergió $node. Esperado: $expected. Actual: $result" >&2
    exit 1
}

exercise_campus() {
    local origin="$1" destination="$2" user="$3" password="$4" campus="$5" destination_user="$6" destination_password="$7"
    local inserted id
    inserted=$(query "$origin" "$user" "$password" "
        INSERT INTO sig.edificios (nombre, codigo, geom)
        SELECT 'Edificio de prueba temporal', 'PRUEBA-CRUD', geom
        FROM sig.edificios WHERE campus_id = $campus LIMIT 1
        RETURNING id, campus_id")
    id="${inserted%%|*}"
    require_equal "${inserted#*|}" "$campus" "pertenencia del edificio nuevo"
    if (( (id - campus) % 5 != 0 )); then
        echo "El id $id no pertenece a la secuencia del campus $campus" >&2
        exit 1
    fi
    wait_for central postgres "$PGPASSWORD" "SELECT count(*) FROM sig.edificios WHERE id = $id" 1
    wait_for "$destination" "$destination_user" "$destination_password" "SELECT count(*) FROM sig.edificios WHERE id = $id" 1

    require_equal "$(query "$origin" "$user" "$password" "UPDATE sig.edificios SET nombre = 'Edificio editado desde la vista' WHERE id = $id RETURNING nombre")" \
        'Edificio editado desde la vista' 'edición local'
    wait_for central postgres "$PGPASSWORD" "SELECT nombre FROM sig.edificios WHERE id = $id" 'Edificio editado desde la vista'
    wait_for "$destination" "$destination_user" "$destination_password" "SELECT nombre FROM sig.edificios WHERE id = $id" 'Edificio editado desde la vista'

    require_equal "$(query "$origin" "$user" "$password" "DELETE FROM sig.edificios WHERE id = $id RETURNING id")" "$id" 'borrado local'
    wait_for central postgres "$PGPASSWORD" "SELECT count(*) FROM sig.edificios WHERE id = $id" 0
    wait_for "$destination" "$destination_user" "$destination_password" "SELECT count(*) FROM sig.edificios WHERE id = $id" 0
    echo "CRUD y dos saltos verificados desde $origin"
}

require_equal "$(query central demo_cartago "$SIGTEC_CARTAGO_PASSWORD" 'SELECT auth.mi_campus()')" 1 'autenticación de Cartago'
require_equal "$(query central demo_san_carlos "$SIGTEC_SAN_CARLOS_PASSWORD" 'SELECT auth.mi_campus()')" 3 'autenticación de San Carlos'
require_equal "$(query cartago demo_cartago "$SIGTEC_CARTAGO_PASSWORD" 'SELECT count(*) FROM sig.edificios')" 2 'vista global de Cartago'
require_equal "$(query san_carlos demo_san_carlos "$SIGTEC_SAN_CARLOS_PASSWORD" 'SELECT count(*) FROM sig.edificios')" 2 'vista global de San Carlos'

require_rejected cartago demo_cartago "$SIGTEC_CARTAGO_PASSWORD" \
    "UPDATE sig.edificios SET nombre = 'Cambio indebido' WHERE campus_id = 3"
require_rejected san_carlos demo_san_carlos "$SIGTEC_SAN_CARLOS_PASSWORD" \
    "DELETE FROM sig.edificios WHERE campus_id = 1"
require_rejected cartago demo_cartago "$SIGTEC_CARTAGO_PASSWORD" \
    "INSERT INTO sig.edificios (campus_id, nombre, geom) SELECT 3, 'Ajeno', geom FROM sig.edificios LIMIT 1"
require_rejected cartago demo_cartago "$SIGTEC_CARTAGO_PASSWORD" \
    'UPDATE sig.edificios SET id = id + 5 WHERE campus_id = 1'
require_rejected san_carlos demo_san_carlos "$SIGTEC_SAN_CARLOS_PASSWORD" \
    'UPDATE sig.edificios SET campus_id = 1 WHERE campus_id = 3'
require_rejected cartago demo_cartago "$SIGTEC_CARTAGO_PASSWORD" \
    'SELECT count(*) FROM cartago.edificios'
require_equal "$(query cartago demo_cartago "$SIGTEC_CARTAGO_PASSWORD" \
    "BEGIN; UPDATE sig.edificios SET nombre = 'Cambio revertido' WHERE campus_id = 1; ROLLBACK; SELECT count(*) FROM sig.edificios WHERE nombre = 'Cambio revertido'")" \
    0 'rollback local'

exercise_campus cartago san_carlos demo_cartago "$SIGTEC_CARTAGO_PASSWORD" 1 demo_san_carlos "$SIGTEC_SAN_CARLOS_PASSWORD"
exercise_campus san_carlos cartago demo_san_carlos "$SIGTEC_SAN_CARLOS_PASSWORD" 3 demo_cartago "$SIGTEC_CARTAGO_PASSWORD"
echo 'Pruebas SQL de autenticación, permisos, CRUD y replicación completadas.'

#!/usr/bin/env bash
set -Eeuo pipefail

# Se ejecuta dentro del servicio bootstrap, después de sincronizar las 40 filas.
campuses=(cartago san_jose san_carlos alajuela limon)
campus_ids=(1 2 3 4 5)
password_vars=(SIGTEC_CARTAGO_PASSWORD SIGTEC_SAN_JOSE_PASSWORD SIGTEC_SAN_CARLOS_PASSWORD SIGTEC_ALAJUELA_PASSWORD SIGTEC_LIMON_PASSWORD)
layers=(edificios carreteras aceras parqueos zonas_verdes puntos_interes iluminacion accesibilidad)
active_origin=''
active_user=''
active_password=''
active_layer=''
active_id=''

password_for() {
    local name="${password_vars[$1]}"
    printf '%s' "${!name}"
}

query() {
    local node="$1" user="$2" password="$3" sql="$4"
    PGPASSWORD="$password" psql -X -q -w -At -v ON_ERROR_STOP=1 \
        -h "$node" -U "$user" -d sig_tec -c "$sql"
}

cleanup() {
    if [[ -n "$active_id" ]]; then
        if ! query "$active_origin" "$active_user" "$active_password" \
            "DELETE FROM sig.$active_layer WHERE id = $active_id" >/dev/null; then
            echo "No se pudo limpiar la fila temporal $active_layer/$active_id en $active_origin" >&2
        fi
    fi
}
trap cleanup EXIT

require_equal() {
    if [[ "$1" != "$2" ]]; then
        echo "Se esperaba '$2' y se obtuvo '$1': $3" >&2
        exit 1
    fi
}

require_rejected() {
    local result
    if result=$(query "$@" 2>&1); then
        echo "Una operación prohibida fue aceptada: $4" >&2
        exit 1
    fi
    if [[ "$result" != *"permission denied"* && "$result" != *"Solo puede"* && "$result" != *"inmutables"* ]]; then
        echo "La operación falló por un motivo inesperado: $result" >&2
        exit 1
    fi
}

wait_for() {
    local node="$1" user="$2" password="$3" sql="$4" expected="$5" result=''
    for ((attempt = 0; attempt < 60; attempt++)); do
        result=$(query "$node" "$user" "$password" "$sql")
        if [[ "$result" == "$expected" ]]; then return; fi
        sleep 1
    done
    echo "No convergió $node para [$sql]. Esperado: $expected. Actual: $result" >&2
    exit 1
}

columns_for() {
    case "$1" in
        edificios) echo 'nombre, codigo, area, pisos' ;;
        carreteras) echo 'nombre, tipo, superficie' ;;
        aceras) echo 'material, ancho, condicion' ;;
        parqueos) echo 'capacidad, tipo, disponibilidad' ;;
        zonas_verdes) echo 'area, tipo_vegetacion' ;;
        puntos_interes) echo 'nombre, tipo' ;;
        iluminacion) echo 'codigo, potencia, estado' ;;
        accesibilidad) echo 'tipo' ;;
    esac
}

editable_field_for() {
    case "$1" in
        edificios|carreteras|puntos_interes) echo nombre ;;
        aceras) echo material ;;
        parqueos|accesibilidad) echo tipo ;;
        zonas_verdes) echo tipo_vegetacion ;;
        iluminacion) echo codigo ;;
    esac
}

geometry_type_for() {
    case "$1" in
        edificios|parqueos|zonas_verdes) echo ST_Polygon ;;
        carreteras|aceras|accesibilidad) echo ST_LineString ;;
        puntos_interes|iluminacion) echo ST_Point ;;
    esac
}

check_inventory() {
    local layer geometry_type union_sql='' i
    for layer in "${layers[@]}"; do
        geometry_type=$(geometry_type_for "$layer")
        require_equal "$(query central postgres "$PGPASSWORD" "
            SELECT count(*) || '|' || count(DISTINCT campus_id) || '|' ||
                   bool_and(ST_IsValid(geom)) || '|' ||
                   bool_and(ST_SRID(geom) = 8908) || '|' ||
                   bool_and(ST_GeometryType(geom) = '$geometry_type') || '|' ||
                   bool_and(mod(id - campus_id, 5) = 0)
            FROM sig.$layer")" '5|5|true|true|true|true' "inventario y geometría de $layer"
        require_equal "$(query central postgres "$PGPASSWORD" "
            SELECT data_type FROM information_schema.columns
            WHERE table_schema = 'sig' AND table_name = '$layer' AND column_name = 'id'")" \
            bigint "tipo global del id en $layer"
        for ((i = 0; i < ${#campuses[@]}; i++)); do
            require_equal "$(query "${campuses[i]}" "demo_${campuses[i]}" "$(password_for "$i")" \
                "SELECT count(*) FROM sig.$layer")" 5 "vista $layer en ${campuses[i]}"
        done
        if [[ -n "$union_sql" ]]; then union_sql+=' UNION ALL '; fi
        union_sql+="SELECT id, campus_id FROM sig.$layer"
    done
    require_equal "$(query central postgres "$PGPASSWORD" "
        SELECT count(*) || '|' || count(DISTINCT id) || '|' ||
               bool_and(mod(id - campus_id, 5) = 0)
        FROM ($union_sql) AS todas")" '40|40|true' 'identificadores globales de las 40 semillas'
    echo 'Inventario: 40 filas, ocho geometrías tipadas y cinco campus por vista.'
}

check_subscriptions() {
    local i node expected
    for node in central "${campuses[@]}"; do
        expected=1
        if [[ "$node" == central ]]; then expected=5; fi
        require_equal "$(query "$node" postgres "$PGPASSWORD" \
            'SELECT count(*) FROM pg_subscription WHERE subenabled')" "$expected" \
            "suscripciones activas de $node"
        require_equal "$(query "$node" postgres "$PGPASSWORD" \
            'SELECT count(*) FROM pg_subscription')" "$expected" \
            "suscripciones sin duplicados de $node"
    done
    for ((i = 0; i < ${#campuses[@]}; i++)); do
        require_equal "$(query central "demo_${campuses[i]}" "$(password_for "$i")" \
            'SELECT auth.mi_campus()')" "${campus_ids[i]}" \
            "autenticación de ${campuses[i]}"
    done
    echo 'Autenticación y diez suscripciones activas comprobadas.'
}

exercise_layer() {
    local i="$1" layer="$2" peer_index
    local origin="${campuses[i]}" campus="${campus_ids[i]}" user="demo_${campuses[i]}"
    local password peer peer_user peer_password columns field inserted id updated lookup
    password=$(password_for "$i")
    columns=$(columns_for "$layer")
    field=$(editable_field_for "$layer")

    inserted=$(query "$origin" "$user" "$password" "
        INSERT INTO sig.$layer ($columns, geom)
        SELECT $columns, ST_Translate(geom, 10, 10)
        FROM sig.$layer WHERE campus_id = $campus ORDER BY id LIMIT 1
        RETURNING id, campus_id")
    id="${inserted%%|*}"
    require_equal "${inserted#*|}" "$campus" "pertenencia de $layer en $origin"
    if [[ ! "$id" =~ ^[0-9]+$ ]] || (( (id - campus) % 5 != 0 )); then
        echo "ID incorrecto para $layer en $origin: $id" >&2
        exit 1
    fi
    active_origin="$origin"
    active_user="$user"
    active_password="$password"
    active_layer="$layer"
    active_id="$id"
    lookup="SELECT count(*) FROM sig.$layer WHERE id = $id"
    wait_for central postgres "$PGPASSWORD" "$lookup" 1
    for ((peer_index = 0; peer_index < ${#campuses[@]}; peer_index++)); do
        if ((peer_index == i)); then continue; fi
        peer="${campuses[peer_index]}"
        peer_user="demo_$peer"
        peer_password=$(password_for "$peer_index")
        wait_for "$peer" "$peer_user" "$peer_password" "$lookup" 1
    done

    updated=$(query "$origin" "$user" "$password" "
        UPDATE sig.$layer
        SET $field = coalesce($field, '') || ' SQL smoke',
            geom = ST_Translate(geom, 2, 2)
        WHERE id = $id
        RETURNING $field, encode(ST_AsEWKB(geom), 'hex')")
    lookup="SELECT $field, encode(ST_AsEWKB(geom), 'hex') FROM sig.$layer WHERE id = $id"
    wait_for central postgres "$PGPASSWORD" "$lookup" "$updated"
    for ((peer_index = 0; peer_index < ${#campuses[@]}; peer_index++)); do
        if ((peer_index == i)); then continue; fi
        peer="${campuses[peer_index]}"
        peer_user="demo_$peer"
        peer_password=$(password_for "$peer_index")
        wait_for "$peer" "$peer_user" "$peer_password" "$lookup" "$updated"
    done

    require_equal "$(query "$origin" "$user" "$password" \
        "DELETE FROM sig.$layer WHERE id = $id RETURNING id")" "$id" \
        "borrado de $layer en $origin"
    wait_for central postgres "$PGPASSWORD" "SELECT count(*) FROM sig.$layer WHERE id = $id" 0
    for ((peer_index = 0; peer_index < ${#campuses[@]}; peer_index++)); do
        if ((peer_index == i)); then continue; fi
        peer="${campuses[peer_index]}"
        peer_user="demo_$peer"
        peer_password=$(password_for "$peer_index")
        wait_for "$peer" "$peer_user" "$peer_password" "SELECT count(*) FROM sig.$layer WHERE id = $id" 0
    done
    active_id=''
}

check_permissions_and_rollback() {
    local i layer origin campus user password remote_id seed_id before after
    for ((i = 0; i < ${#campuses[@]}; i++)); do
        origin="${campuses[i]}"
        campus="${campus_ids[i]}"
        user="demo_$origin"
        password=$(password_for "$i")
        for layer in "${layers[@]}"; do
            remote_id=$(query "$origin" "$user" "$password" \
                "SELECT id FROM sig.$layer WHERE campus_id <> $campus ORDER BY id LIMIT 1")
            require_rejected "$origin" "$user" "$password" \
                "UPDATE sig.$layer SET geom = geom WHERE id = $remote_id"
            require_rejected "$origin" "$user" "$password" \
                "DELETE FROM sig.$layer WHERE id = $remote_id"
            require_rejected "$origin" "$user" "$password" \
                "SELECT count(*) FROM $origin.$layer"
        done
        require_rejected "$origin" "$user" "$password" \
            "INSERT INTO sig.edificios (campus_id, nombre, geom)
             SELECT 9, 'Ajeno', geom FROM sig.edificios WHERE campus_id = $campus LIMIT 1"
        require_rejected "$origin" "$user" "$password" \
            "UPDATE sig.edificios SET id = id + 5 WHERE campus_id = $campus"
        require_rejected "$origin" "$user" "$password" \
            "UPDATE sig.edificios SET campus_id = 9 WHERE campus_id = $campus"

        seed_id=$(query "$origin" "$user" "$password" \
            "SELECT id FROM sig.edificios WHERE campus_id = $campus ORDER BY id LIMIT 1")
        before=$(query "$origin" "$user" "$password" \
            "SELECT nombre FROM sig.edificios WHERE id = $seed_id")
        after=$(query "$origin" "$user" "$password" "
            BEGIN;
            UPDATE sig.edificios SET nombre = nombre || ' ROLLBACK' WHERE id = $seed_id;
            ROLLBACK;
            SELECT nombre FROM sig.edificios WHERE id = $seed_id")
        require_equal "$after" "$before" "ROLLBACK local de $origin"
        require_equal "$(query central postgres "$PGPASSWORD" \
            "SELECT nombre FROM sig.edificios WHERE id = $seed_id")" "$before" \
            "ROLLBACK visible en central desde $origin"
    done
    echo 'Permisos por fila, tablas físicas y ROLLBACK comprobados.'
}

check_subscriptions
check_inventory
check_permissions_and_rollback
for ((i = 0; i < ${#campuses[@]}; i++)); do
    for layer in "${layers[@]}"; do
        exercise_layer "$i" "$layer"
    done
    echo "CRUD y ambos saltos comprobados para ${campuses[i]} en ocho capas."
done
check_inventory
check_subscriptions
echo 'Pruebas SQL de cinco campus y ocho capas completadas.'

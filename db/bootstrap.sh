#!/usr/bin/env bash
set -Eeuo pipefail

for required in PGPASSWORD SIGTEC_CARTAGO_PASSWORD SIGTEC_SAN_JOSE_PASSWORD SIGTEC_SAN_CARLOS_PASSWORD SIGTEC_ALAJUELA_PASSWORD SIGTEC_LIMON_PASSWORD SIGTEC_REPLICATION_PASSWORD; do
    if [[ -z "${!required:-}" ]]; then
        echo "Falta $required en .env" >&2
        exit 1
    fi
done

# libpq connection strings stored by subscriptions use these passwords without escaping.
for secret in SIGTEC_CARTAGO_PASSWORD SIGTEC_SAN_JOSE_PASSWORD SIGTEC_SAN_CARLOS_PASSWORD SIGTEC_ALAJUELA_PASSWORD SIGTEC_LIMON_PASSWORD SIGTEC_REPLICATION_PASSWORD; do
    if [[ ! "${!secret}" =~ ^[A-Za-z0-9]{24,}$ ]]; then
        echo "$secret requiere al menos 24 caracteres alfanuméricos" >&2
        exit 1
    fi
done

campuses=(cartago san_jose san_carlos alajuela limon)
declare -A campus_ids=(
    [cartago]=1 [san_jose]=2 [san_carlos]=3 [alajuela]=4 [limon]=5
)
declare -A upstream_publications=(
    [cartago]=pub_cartago_edificios
    [san_jose]=pub_san_jose_capas
    [san_carlos]=pub_san_carlos_edificios
    [alajuela]=pub_alajuela_capas
    [limon]=pub_limon_capas
)
declare -A downstream_publications=(
    [cartago]=pub_san_jose_capas,pub_san_carlos_edificios,pub_alajuela_capas,pub_limon_capas,pub_layer_styles
    [san_jose]=pub_cartago_edificios,pub_san_carlos_edificios,pub_alajuela_capas,pub_limon_capas,pub_layer_styles
    [san_carlos]=pub_cartago_edificios,pub_san_jose_capas,pub_alajuela_capas,pub_limon_capas,pub_layer_styles
    [alajuela]=pub_cartago_edificios,pub_san_jose_capas,pub_san_carlos_edificios,pub_limon_capas,pub_layer_styles
    [limon]=pub_cartago_edificios,pub_san_jose_capas,pub_san_carlos_edificios,pub_alajuela_capas,pub_layer_styles
)

psql_node() {
    local node="$1"
    shift
    psql -X -q -w -v ON_ERROR_STOP=1 -h "$node" -U postgres -d sig_tec "$@"
}

run_file() {
    local node="$1" file="$2"
    psql_node "$node" -v "node=$node" \
        -v "campus_id=${campus_ids[$node]:-0}" \
        -v "is_cartago=$([[ "$node" == cartago ]] && echo true || echo false)" \
        -v "is_san_jose=$([[ "$node" == san_jose ]] && echo true || echo false)" \
        -v "is_san_carlos=$([[ "$node" == san_carlos ]] && echo true || echo false)" \
        -v "is_alajuela=$([[ "$node" == alajuela ]] && echo true || echo false)" \
        -v "is_limon=$([[ "$node" == limon ]] && echo true || echo false)" \
        -f "/db/$file"
}

wait_ready() {
    local node="$1" subscription="$2" expected="$3" remaining=300
    local result='0:0'
    while (( remaining > 0 )); do
        result=$(psql_node "$node" -At -c "
            SELECT count(*)::text || ':' || count(*) FILTER (WHERE r.srsubstate = 'r')::text
            FROM pg_subscription s
            JOIN pg_subscription_rel r ON r.srsubid = s.oid
            WHERE s.subname = '$subscription'")
        if [[ "$result" == "$expected:$expected" ]]; then
            echo "$node/$subscription: $expected tablas listas"
            return
        fi
        sleep 2
        ((remaining -= 2))
    done
    echo "Tiempo agotado al sincronizar $node/$subscription. Estado: $result" >&2
    exit 1
}

check_subscription() {
    local node="$1" subscription="$2" slot="$3" expected_publications="$4"
    local state
    state=$(psql_node "$node" -At -c "
        SELECT subslotname || ':' || array_to_string(subpublications, ',')
        FROM pg_subscription WHERE subname = '$subscription'")
    if [[ "$state" != "$slot:$expected_publications" ]]; then
        echo "Suscripción $node/$subscription distinta a la esperada: $state" >&2
        exit 1
    fi
}

for node in central "${campuses[@]}"; do
    echo "Preparando esquema de $node"
    run_file "$node" schema.sql
    run_file "$node" seed.sql
    run_file "$node" publications.sql
done

# Create named slots before subscriptions so a retry can resume after a partial bootstrap.
for campus in "${campuses[@]}"; do
    psql_node "$campus" -v "slot_name=slot_central_$campus" -f /db/slot.sql
done
run_file central subscriptions.sql
for campus in "${campuses[@]}"; do
    check_subscription central "sub_central_$campus" "slot_central_$campus" "${upstream_publications[$campus]}"
done
for campus in "${campuses[@]}"; do
    wait_ready central "sub_central_$campus" 8
done

for campus in "${campuses[@]}"; do
    psql_node central -v "slot_name=slot_${campus}_central" -f /db/slot.sql
done
for campus in "${campuses[@]}"; do
    run_file "$campus" subscriptions.sql
done
for campus in "${campuses[@]}"; do
    check_subscription "$campus" "sub_${campus}_central" "slot_${campus}_central" "${downstream_publications[$campus]}"
done
for campus in "${campuses[@]}"; do
    wait_ready "$campus" "sub_${campus}_central" 33
done

echo 'SIG-TEC: central y los cinco campus sincronizados.'

#!/usr/bin/env bash
set -Eeuo pipefail

for required in PGPASSWORD SIGTEC_CARTAGO_PASSWORD SIGTEC_SAN_CARLOS_PASSWORD SIGTEC_REPLICATION_PASSWORD; do
    if [[ -z "${!required:-}" ]]; then
        echo "Falta $required en .env" >&2
        exit 1
    fi
done

# libpq connection strings stored by subscriptions use these passwords without escaping.
for secret in SIGTEC_CARTAGO_PASSWORD SIGTEC_SAN_CARLOS_PASSWORD SIGTEC_REPLICATION_PASSWORD; do
    if [[ ! "${!secret}" =~ ^[A-Za-z0-9]{24,}$ ]]; then
        echo "$secret requiere al menos 24 caracteres alfanuméricos" >&2
        exit 1
    fi
done

psql_node() {
    local node="$1"
    shift
    psql -X -q -w -v ON_ERROR_STOP=1 -h "$node" -U postgres -d sig_tec "$@"
}

run_file() {
    local node="$1" file="$2"
    psql_node "$node" -v "node=$node" \
        -v "is_cartago=$([[ "$node" == cartago ]] && echo true || echo false)" \
        -v "is_san_carlos=$([[ "$node" == san_carlos ]] && echo true || echo false)" \
        -f "/db/$file"
}

wait_ready() {
    local node="$1" subscription="$2" expected="$3" remaining=60
    local result
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

for node in central cartago san_carlos; do
    echo "Preparando esquema de $node"
    run_file "$node" schema.sql
    run_file "$node" seed.sql
    run_file "$node" publications.sql
done

# Create named slots before subscriptions so a retry can resume after a partial bootstrap.
psql_node cartago -v slot_name=slot_central_cartago -f /db/slot.sql
psql_node san_carlos -v slot_name=slot_central_san_carlos -f /db/slot.sql
run_file central subscriptions.sql
check_subscription central sub_central_cartago slot_central_cartago pub_cartago_edificios
check_subscription central sub_central_san_carlos slot_central_san_carlos pub_san_carlos_edificios
wait_ready central sub_central_cartago 1
wait_ready central sub_central_san_carlos 1

psql_node central -v slot_name=slot_cartago_central -f /db/slot.sql
psql_node central -v slot_name=slot_san_carlos_central -f /db/slot.sql
run_file cartago subscriptions.sql
run_file san_carlos subscriptions.sql
check_subscription cartago sub_cartago_central slot_cartago_central pub_san_carlos_edificios,pub_layer_styles
check_subscription san_carlos sub_san_carlos_central slot_san_carlos_central pub_cartago_edificios,pub_layer_styles
wait_ready cartago sub_cartago_central 2
wait_ready san_carlos sub_san_carlos_central 2

echo 'SIG-TEC: Cartago, central y San Carlos sincronizados.'

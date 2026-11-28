#!/usr/bin/env python3
"""Demuestra desconexión y convergencia sin modificar las filas de muestra.

Requiere el proyecto Compose original ``iiiproyectobasesii`` y sus seis nodos
saludables. Lee las claves de ``.env`` y nunca las envía por argv ni las imprime.
La prueba genera un edificio temporal de Cartago y lo elimina en ``finally``.
No ejecutar mientras otra persona edita la base o se prueba PITR.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import psycopg


ROOT = Path(__file__).resolve().parents[1]
PROJECT = "iiiproyectobasesii"
NODES = {
    "central": (55430, "demo_cartago", "SIGTEC_CARTAGO_PASSWORD"),
    "cartago": (55431, "demo_cartago", "SIGTEC_CARTAGO_PASSWORD"),
    "san_jose": (55432, "demo_san_jose", "SIGTEC_SAN_JOSE_PASSWORD"),
    "san_carlos": (55433, "demo_san_carlos", "SIGTEC_SAN_CARLOS_PASSWORD"),
    "alajuela": (55434, "demo_alajuela", "SIGTEC_ALAJUELA_PASSWORD"),
    "limon": (55435, "demo_limon", "SIGTEC_LIMON_PASSWORD"),
}
MARKER_PREFIX = "SIGTEC_FALLA_"


class DemoError(Exception):
    """Fallo con un mensaje apto para mostrar sin credenciales."""


def command(*args):
    try:
        result = subprocess.run(
            args, cwd=ROOT, capture_output=True, text=True, timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DemoError(f"No se pudo ejecutar {args[0]}.") from error
    if result.returncode:
        raise DemoError(f"Falló {args[0]} (código {result.returncode}); diagnóstico omitido.")
    return result.stdout.strip()


def compose(*args):
    return command("docker", "compose", "-p", PROJECT, *args)


def container(node):
    return f"{PROJECT}-{node}-1"


def mounts():
    """Comprueba el proyecto y los volúmenes de datos antes de detener nodos."""
    result = {}
    for node in NODES:
        payload = command("docker", "inspect", "--format", "{{json .Mounts}}", container(node))
        sources = json.loads(payload)
        data = [item for item in sources
                if item.get("Destination") == "/var/lib/postgresql/data"]
        expected = f"{PROJECT}_{node}_data"
        if len(data) != 1 or data[0].get("Type") != "volume" or data[0].get("Name") != expected:
            raise DemoError(f"El volumen PGDATA de {node} no es el esperado; detenerse.")
        result[node] = expected
    return result


def health():
    states = {}
    for line in compose("ps", "--format", "json").splitlines():
        if line.strip():
            item = json.loads(line)
            states[item["Service"]] = (item.get("Name"), item.get("State"), item.get("Health"))
    for node in NODES:
        if states.get(node) != (container(node), "running", "healthy"):
            raise DemoError(f"{node} no está saludable; detenerse.")


def is_running(node):
    return command("docker", "inspect", "--format", "{{.State.Running}}", container(node)) == "true"


def wait_healthy(node, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_running(node):
            status = command("docker", "inspect", "--format", "{{.State.Health.Status}}", container(node))
            if status == "healthy":
                return
        time.sleep(1)
    raise DemoError(f"{node} no recuperó salud dentro de {timeout} s.")


def credentials():
    path = ROOT / ".env"
    if not path.is_file():
        raise DemoError("Falta el archivo local .env.")
    values = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name.strip()] = value
    for _, _, variable in NODES.values():
        values[variable] = os.environ.get(variable) or values.get(variable)
        if not values[variable]:
            raise DemoError(f"Falta {variable} en .env.")
    return values


def connect(node, values):
    port, user, variable = NODES[node]
    return psycopg.connect(
        host="127.0.0.1", port=port, dbname="sig_tec", user=user,
        password=values[variable], connect_timeout=5,
        options="-c statement_timeout=7000", autocommit=True,
        application_name="sig-tec-outage-demo",
    )


def count(node, values, marker=None):
    with connect(node, values) as db:
        if marker is None:
            return db.execute("SELECT count(*) FROM sig.edificios").fetchone()[0]
        return db.execute(
            "SELECT count(*) FROM sig.edificios WHERE codigo = %s", (marker,)
        ).fetchone()[0]


def wait_count(node, values, marker, expected, timeout):
    started = time.monotonic()
    deadline = started + timeout
    while time.monotonic() < deadline:
        try:
            if count(node, values, marker) == expected:
                return round(time.monotonic() - started, 2)
        except psycopg.OperationalError:
            pass
        time.sleep(1)
    raise DemoError(f"{node} no convergió a {expected} filas temporales en {timeout} s.")


def insert_local(db, marker, scenario):
    row = db.execute(
        """INSERT INTO sig.edificios (nombre, codigo, area, pisos, geom)
           SELECT %s, %s, area, pisos, ST_Translate(geom, 10, 10)
           FROM sig.edificios WHERE campus_id = 1 ORDER BY id LIMIT 1
           RETURNING id, campus_id""",
        (f"Demostración de caída {scenario}", marker),
    ).fetchone()
    if row is None or row[1] != 1 or (row[0] - 1) % 5:
        raise DemoError("Cartago no asignó el edificio temporal esperado.")
    return row[0]


def cleanup(values, marker):
    # El marcador permite limpiar incluso si se perdió la respuesta del INSERT.
    with connect("cartago", values) as db:
        rows = db.execute(
            "DELETE FROM sig.edificios WHERE campus_id = 1 AND codigo = %s RETURNING id",
            (marker,),
        ).fetchall()
    if len(rows) > 1:
        raise DemoError("El marcador temporal identificó más de una fila.")
    for node in NODES:
        wait_count(node, values, marker, 0, 90)


def run(scenario, hold_seconds, timeout):
    values = credentials()
    original_mounts = mounts()
    health()
    original_counts = {node: count(node, values) for node in NODES}
    if set(original_counts.values()) != {5}:
        raise DemoError("Las vistas no muestran las cinco filas originales; detenerse.")

    target = "san_carlos" if scenario == "campus" else "central"
    marker = MARKER_PREFIX + uuid4().hex
    temporary_id = None
    stop_attempted = False
    problem = None
    cleanup_problem = None
    result = {
        "scenario": scenario,
        "project": PROJECT,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "stopped_node": target,
        "original_counts": original_counts,
    }
    try:
        # Mantener abierta la conexión local antes y durante la caída.
        with connect("cartago", values) as local:
            stop_attempted = True
            compose("stop", target)
            if is_running(target):
                raise DemoError(f"{target} siguió en ejecución después de stop.")
            print(f"{target}: detenido; sesión de Cartago conservada.", flush=True)

            temporary_id = insert_local(local, marker, scenario)
            if local.execute(
                "SELECT count(*) FROM sig.edificios WHERE id = %s AND campus_id = 1",
                (temporary_id,),
            ).fetchone()[0] != 1:
                raise DemoError("La edición local no quedó visible en Cartago.")
            result["temporary_id"] = temporary_id
            result["local_write_while_node_down"] = True
            print(f"Cartago: alta local confirmada, id={temporary_id}.", flush=True)

            if scenario == "campus":
                result["central_before_restart_seconds"] = wait_count(
                    "central", values, marker, 1, timeout
                )
                print("Central: recibió el alta mientras San Carlos estaba detenido.", flush=True)
            elif count("san_carlos", values, marker) != 0:
                raise DemoError("San Carlos recibió el alta mientras el central estaba detenido.")

            compose("start", target)
            wait_healthy(target, timeout)
            print(f"{target}: saludable de nuevo.", flush=True)
            result["convergence_seconds"] = {
                node: wait_count(node, values, marker, 1, timeout)
                for node in NODES if node != "cartago"
            }
            print("Los seis nodos ven el mismo edificio temporal.", flush=True)
            if hold_seconds:
                print(f"Pausa de {hold_seconds} s para observar QGIS.", flush=True)
                time.sleep(hold_seconds)
    except Exception as error:
        problem = error
    finally:
        # Volver a iniciar el nodo aunque stop/insert/replicación hayan fallado.
        if stop_attempted:
            try:
                compose("start", target)
                wait_healthy(target, timeout)
            except Exception as error:
                problem = problem or error
        try:
            cleanup(values, marker)
            result["temporary_row_removed_everywhere"] = True
        except Exception as error:
            cleanup_problem = error
        try:
            health()
            if mounts() != original_mounts:
                raise DemoError("Cambiaron los montajes PGDATA.")
            final_counts = {node: count(node, values) for node in NODES}
            if final_counts != original_counts:
                raise DemoError("Los conteos finales difieren del inventario inicial.")
            result["six_nodes_healthy"] = True
            result["data_volume_mounts_unchanged"] = True
            result["final_counts"] = final_counts
        except Exception as error:
            problem = problem or error

    if cleanup_problem is not None:
        raise DemoError(
            f"No se pudo completar o verificar la limpieza de {marker}; "
            "revisar la fila temporal antes de repetir."
        ) from cleanup_problem
    if problem is not None:
        if isinstance(problem, DemoError):
            raise problem
        raise DemoError(f"Falló {scenario} ({type(problem).__name__}); diagnóstico omitido.") from problem
    result["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("campus", "central"), required=True)
    parser.add_argument("--hold-seconds", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    if not 0 <= args.hold_seconds <= 120 or not 30 <= args.timeout <= 300:
        parser.error("hold-seconds debe estar entre 0 y 120; timeout entre 30 y 300")
    try:
        print(json.dumps(run(args.scenario, args.hold_seconds, args.timeout),
                         ensure_ascii=False, indent=2), flush=True)
    except DemoError as error:
        print("DETENER: " + str(error), file=sys.stderr)
        return 1
    except Exception:
        print("DETENER: fallo inesperado; diagnóstico omitido para proteger credenciales.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

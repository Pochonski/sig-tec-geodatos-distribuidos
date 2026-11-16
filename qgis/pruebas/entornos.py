"""Configuración de las pruebas contra una base: el simulador o la base integrada.

Variables de entorno:

- SIG_TEC_ENTORNO: `simulador` (predeterminado, qgis/entorno-prueba) o `integracion` (compose.yaml y db/).
- SIG_TEC_HOST: servidor de los nodos. Desde un contenedor de QGIS, `host.docker.internal`.
- SIG_TEC_PROYECTO_COMPOSE: proyecto Compose de los nodos, para ejecutar psql con docker exec.
- SIG_TEC_ENV: archivo .env de la integración; por omisión, el de la raíz del repositorio.

Las contraseñas se leen de los archivos .env o del entorno y nunca se imprimen.
"""

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

RAIZ_REPOSITORIO = Path(__file__).resolve().parents[2]
HOST = os.environ.get("SIG_TEC_HOST", "127.0.0.1")


@dataclass(frozen=True)
class Cuenta:
    usuario: str
    clave: str = field(repr=False)


@dataclass(frozen=True)
class Entorno:
    nombre: str
    puerto_base: int
    cuentas: dict = field(repr=False)
    proyecto_compose: str
    servicios: dict
    cuenta_sin_campus: Cuenta = field(default=None, repr=False)

    def cuenta(self, campus_id):
        return self.cuentas[campus_id]

    @property
    def servicios_campus(self):
        return [servicio for campus_id, servicio in sorted(self.servicios.items()) if campus_id]


def leer_env(ruta):
    """Lee pares NOMBRE=valor sin interpretar ni mostrar los valores."""
    valores = {}
    if not ruta.exists():
        return valores
    for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            nombre, valor = linea.split("=", 1)
            valores[nombre.strip()] = valor.strip().strip("\"'")
    return valores


def simulador():
    valores = leer_env(RAIZ_REPOSITORIO / "qgis" / "entorno-prueba" / ".env")
    clave = os.environ.get("CLAVE_PRUEBA") or valores.get("CLAVE_PRUEBA") or "sigtec-prueba"
    return Entorno(
        nombre="simulador",
        puerto_base=int(valores.get("PUERTO_BASE", "56430")),
        cuentas={
            1: Cuenta("cartago_prueba", clave),
            2: Cuenta("san_jose_prueba", clave),
            3: Cuenta("san_carlos_prueba", clave),
        },
        proyecto_compose=os.environ.get("SIG_TEC_PROYECTO_COMPOSE", "sig-tec-qgis"),
        servicios={0: "central", 1: "cartago", 2: "san-jose", 3: "san-carlos"},
        cuenta_sin_campus=Cuenta("sin_campus_prueba", clave),
    )


def integracion():
    ruta = Path(os.environ.get("SIG_TEC_ENV", RAIZ_REPOSITORIO / ".env"))
    valores = leer_env(ruta)
    cuentas = {}
    for campus_id, nombre in enumerate(("cartago", "san_jose", "san_carlos", "alajuela", "limon"), start=1):
        variable = f"SIGTEC_{nombre.upper()}_PASSWORD"
        clave = os.environ.get(variable) or valores.get(variable)
        if not clave:
            raise RuntimeError(f"Falta {variable} en {ruta}")
        cuentas[campus_id] = Cuenta(f"demo_{nombre}", clave)
    if len({cuenta.clave for cuenta in cuentas.values()}) != len(cuentas):
        raise RuntimeError(f"Las contraseñas de las cuentas demo_* de {ruta} deben ser distintas")
    return Entorno(
        nombre="integracion",
        puerto_base=55430,
        cuentas=cuentas,
        proyecto_compose=os.environ.get("SIG_TEC_PROYECTO_COMPOSE", RAIZ_REPOSITORIO.name.lower()),
        servicios={0: "central", 1: "cartago", 2: "san_jose", 3: "san_carlos", 4: "alajuela", 5: "limon"},
    )


def actual():
    nombre = os.environ.get("SIG_TEC_ENTORNO", "simulador")
    if nombre == "simulador":
        return simulador()
    if nombre == "integracion":
        return integracion()
    raise RuntimeError(f"SIG_TEC_ENTORNO desconocido: {nombre}")


def contenedor(entorno, servicio):
    """Id del contenedor de un servicio Compose, o None si no está en ejecución."""
    try:
        salida = subprocess.run(
            [
                "docker", "ps", "-q",
                "--filter", f"label=com.docker.compose.project={entorno.proyecto_compose}",
                "--filter", f"label=com.docker.compose.service={servicio}",
            ],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    return salida[0] if salida else None


def psql(entorno, servicio, sql):
    """Ejecuta SQL como administrador por el socket local del contenedor; no usa contraseñas."""
    identificador = contenedor(entorno, servicio)
    if identificador is None:
        raise RuntimeError(f"El servicio {servicio} de {entorno.proyecto_compose} no está en ejecución")
    resultado = subprocess.run(
        ["docker", "exec", "-i", identificador, "psql", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1",
         "-U", "postgres", "-d", "sig_tec"],
        input=sql.encode("utf-8"), capture_output=True, timeout=120,
    )
    if resultado.returncode != 0:
        raise RuntimeError(f"psql falló en {servicio}: {resultado.stderr.decode('utf-8', 'replace').strip()}")
    return resultado.stdout.decode("utf-8")

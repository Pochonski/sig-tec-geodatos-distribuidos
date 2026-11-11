"""Contrato de datos de SIG-TEC usado por el complemento.

Este módulo no importa QGIS para poder probarlo con Python estándar.
"""

from dataclasses import dataclass
from pathlib import Path

BASE_DATOS = "sig_tec"
ESQUEMA_VISTAS = "sig"
COLUMNA_GEOMETRIA = "geom"
CLAVE_PRIMARIA = "id"
SRID = 8908
NOMBRE_ESTILO = "SIG-TEC"
CONSULTA_CAMPUS = "SELECT auth.mi_campus()"
DIRECTORIO_ESTILOS = Path(__file__).resolve().parent / "estilos"

CAMPUS = {
    1: "Cartago",
    2: "San José",
    3: "San Carlos",
    4: "Alajuela",
    5: "Limón",
}


@dataclass(frozen=True)
class Capa:
    vista: str
    titulo: str
    geometria: str
    atributos: tuple

    @property
    def archivo_estilo(self):
        return DIRECTORIO_ESTILOS / f"{self.vista}.qml"


# Diccionario de docs/diseno.md, en el orden en que se apilan en el proyecto (la primera queda arriba).
CAPAS = (
    Capa("puntos_interes", "Puntos de interés", "Point", ("nombre", "tipo")),
    Capa("iluminacion", "Iluminación", "Point", ("codigo", "estado", "potencia")),
    Capa("accesibilidad", "Accesibilidad", "LineString", ("tipo",)),
    Capa("aceras", "Aceras", "LineString", ("material", "condicion", "ancho")),
    Capa("carreteras", "Carreteras", "LineString", ("nombre", "tipo", "superficie")),
    Capa("edificios", "Edificios", "Polygon", ("nombre", "codigo", "area", "pisos")),
    Capa("parqueos", "Parqueos", "Polygon", ("capacidad", "tipo", "disponibilidad")),
    Capa("zonas_verdes", "Zonas verdes", "Polygon", ("area", "tipo_vegetacion")),
)


@dataclass(frozen=True)
class Ajustes:
    """Ubicación de los nodos. El central usa la base de puertos y cada campus base + campus_id."""

    host: str = "127.0.0.1"
    puerto_base: int = 55430
    base_datos: str = BASE_DATOS

    @property
    def puerto_central(self):
        return self.puerto_base

    def puerto_campus(self, campus_id):
        if campus_id not in CAMPUS:
            raise ValueError(f"campus_id desconocido: {campus_id}")
        return self.puerto_base + campus_id


class ErrorSesion(Exception):
    """Error que se muestra tal cual a la persona usuaria."""


CREDENCIALES = "credenciales"
NO_DISPONIBLE = "no_disponible"


def clasificar_error_conexion(mensaje):
    """Distingue credenciales rechazadas de un servidor que no responde."""
    texto = mensaje.lower()
    if "password authentication failed" in texto or ("role" in texto and "does not exist" in texto):
        return CREDENCIALES
    if "no password supplied" in texto or "fe_sendauth" in texto:
        return CREDENCIALES
    return NO_DISPONIBLE


def nombre_campus(campus_id):
    return CAMPUS.get(campus_id, f"campus {campus_id}")

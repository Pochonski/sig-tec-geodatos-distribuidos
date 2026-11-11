"""Integración del complemento con la interfaz de QGIS."""

from pathlib import Path

from qgis.core import QgsSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .configuracion import CAPAS, Ajustes
from .dialogo import DialogoInicioSesion
from .sesion import ESTILO_BASE_DATOS, cargar_capas, extension_campus, iniciar_sesion

MENU = "&SIG-TEC"
PREFIJO_AJUSTES = "sig_tec/"


def leer_ajustes():
    ajustes = QgsSettings()
    predeterminados = Ajustes()
    return Ajustes(
        host=ajustes.value(PREFIJO_AJUSTES + "host", predeterminados.host),
        puerto_base=ajustes.value(PREFIJO_AJUSTES + "puerto_base", predeterminados.puerto_base, type=int),
        base_datos=ajustes.value(PREFIJO_AJUSTES + "base_datos", predeterminados.base_datos),
    )


def guardar_ajustes(ajustes, usuario):
    # La contraseña queda solo en el gestor de autenticación de QGIS.
    configuracion = QgsSettings()
    configuracion.setValue(PREFIJO_AJUSTES + "host", ajustes.host)
    configuracion.setValue(PREFIJO_AJUSTES + "puerto_base", ajustes.puerto_base)
    configuracion.setValue(PREFIJO_AJUSTES + "base_datos", ajustes.base_datos)
    configuracion.setValue(PREFIJO_AJUSTES + "usuario", usuario)


class ComplementoSigTec:
    def __init__(self, iface):
        self.iface = iface
        self.accion = None

    def initGui(self):
        icono = QIcon(str(Path(__file__).resolve().parent / "icono.svg"))
        self.accion = QAction(icono, "Iniciar sesión en SIG-TEC", self.iface.mainWindow())
        self.accion.triggered.connect(self.iniciar_sesion)
        self.iface.addToolBarIcon(self.accion)
        self.iface.addPluginToDatabaseMenu(MENU, self.accion)

    def unload(self):
        self.iface.removePluginDatabaseMenu(MENU, self.accion)
        self.iface.removeToolBarIcon(self.accion)
        self.accion = None

    def iniciar_sesion(self):
        usuario = QgsSettings().value(PREFIJO_AJUSTES + "usuario", "")
        dialogo = DialogoInicioSesion(leer_ajustes(), usuario, self._entrar, self.iface.mainWindow())
        if dialogo.exec():
            self._informar(*dialogo.resultado)

    def _entrar(self, ajustes, usuario, clave):
        sesion = iniciar_sesion(ajustes, usuario, clave)
        carga = cargar_capas(ajustes, sesion)
        guardar_ajustes(ajustes, sesion.usuario)
        extension = extension_campus(carga.capas, sesion.campus_id)
        if extension is not None:
            self.iface.mapCanvas().setExtent(extension)
            self.iface.mapCanvas().refresh()
        return sesion, carga

    def _informar(self, sesion, carga):
        desde_base = sum(origen == ESTILO_BASE_DATOS for origen in carga.estilos.values())
        barra = self.iface.messageBar()
        barra.pushSuccess(
            "SIG-TEC",
            f"Sesión de {sesion.usuario} en {sesion.nombre_campus}: {len(carga.capas)} capas, "
            f"{desde_base} con el estilo compartido del central.",
        )
        sin_compartido = [capa.titulo for capa in CAPAS if carga.estilos.get(capa.vista) != ESTILO_BASE_DATOS]
        if sin_compartido:
            barra.pushWarning(
                "SIG-TEC",
                "Sin estilo compartido en la base para: " + ", ".join(sin_compartido) + ". Se usó el estilo incluido.",
            )

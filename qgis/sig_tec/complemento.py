"""Integración del complemento con la interfaz de QGIS."""

from pathlib import Path

from qgis.core import QgsProject, QgsSettings
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QApplication, QMessageBox

from .configuracion import CAPAS, Ajustes, ErrorSesion
from .dialogo import DialogoInicioSesion
from .sesion import (
    CANCELAR,
    DESCARTAR,
    ESTILO_BASE_DATOS,
    GUARDAR,
    OperacionCancelada,
    cargar_capas,
    extension_campus,
    iniciar_sesion,
    retirar_capas,
)

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


def preguntar_cambios(capas, parent):
    """Pregunta qué hacer con las ediciones sin guardar antes de retirar las capas."""
    caja = QMessageBox(parent)
    caja.setIcon(QMessageBox.Icon.Warning)
    caja.setWindowTitle("SIG-TEC: ediciones sin guardar")
    caja.setText("Estas capas de SIG-TEC tienen ediciones sin guardar: " + ", ".join(c.name() for c in capas) + ".")
    caja.setInformativeText(
        "Para continuar se retiran todas las capas de la sesión actual. "
        "Guarde o descarte las ediciones, o cancele para dejar el proyecto como está."
    )
    caja.setStandardButtons(
        QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
    )
    caja.setDefaultButton(QMessageBox.StandardButton.Cancel)
    # El inicio de sesión corre con el cursor de espera; la pregunta necesita el cursor normal.
    QApplication.setOverrideCursor(Qt.CursorShape.ArrowCursor)
    try:
        caja.exec()
    finally:
        QApplication.restoreOverrideCursor()
    boton = caja.standardButton(caja.clickedButton())
    if boton == QMessageBox.StandardButton.Save:
        return GUARDAR
    if boton == QMessageBox.StandardButton.Discard:
        return DESCARTAR
    return CANCELAR


class ComplementoSigTec:
    def __init__(self, iface):
        self.iface = iface
        self.acciones = []

    def initGui(self):
        icono = QIcon(str(Path(__file__).resolve().parent / "icono.svg"))
        entrar = QAction(icono, "Iniciar sesión en SIG-TEC", self.iface.mainWindow())
        entrar.triggered.connect(self.iniciar_sesion)
        salir = QAction("Cerrar sesión de SIG-TEC", self.iface.mainWindow())
        salir.triggered.connect(self.cerrar_sesion)
        self.iface.addToolBarIcon(entrar)
        self.acciones = [entrar, salir]
        for accion in self.acciones:
            self.iface.addPluginToDatabaseMenu(MENU, accion)

    def unload(self):
        for accion in self.acciones:
            self.iface.removePluginDatabaseMenu(MENU, accion)
        if self.acciones:
            self.iface.removeToolBarIcon(self.acciones[0])
        self.acciones = []

    def _decidir(self, capas):
        return preguntar_cambios(capas, QApplication.activeModalWidget() or self.iface.mainWindow())

    def iniciar_sesion(self):
        usuario = QgsSettings().value(PREFIJO_AJUSTES + "usuario", "")
        dialogo = DialogoInicioSesion(leer_ajustes(), usuario, self._entrar, self.iface.mainWindow())
        if dialogo.exec():
            self._informar(*dialogo.resultado)
        elif dialogo.cancelado:
            self.iface.messageBar().pushInfo("SIG-TEC", "Inicio de sesión cancelado. El proyecto no cambió.")

    def cerrar_sesion(self):
        barra = self.iface.messageBar()
        try:
            retiradas = retirar_capas(QgsProject.instance(), self._decidir)
        except OperacionCancelada:
            barra.pushInfo("SIG-TEC", "Cierre de sesión cancelado. El proyecto no cambió.")
            return
        except ErrorSesion as error:
            barra.pushCritical("SIG-TEC", str(error))
            return
        barra.pushSuccess("SIG-TEC", f"Sesión cerrada: se retiraron {retiradas} capas.")

    def _entrar(self, ajustes, usuario, clave):
        sesion = iniciar_sesion(ajustes, usuario, clave)
        carga = cargar_capas(ajustes, sesion, decidir=self._decidir)
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

"""Diálogo de inicio de sesión de SIG-TEC."""

from qgis.gui import QgsCollapsibleGroupBox, QgsPasswordLineEdit
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from .configuracion import Ajustes, ErrorSesion
from .sesion import OperacionCancelada


class DialogoInicioSesion(QDialog):
    """Pide la cuenta y ejecuta `al_aceptar(ajustes, usuario, clave)` sin cerrarse si hay un error.

    Si `al_aceptar` lanza OperacionCancelada, el diálogo se cierra con `cancelado` en True.
    """

    def __init__(self, ajustes, usuario, al_aceptar, parent=None):
        super().__init__(parent)
        self._al_aceptar = al_aceptar
        self.resultado = None
        self.cancelado = False
        self.setWindowTitle("Iniciar sesión en SIG-TEC")
        self.setMinimumWidth(380)

        self.usuario = QLineEdit(usuario)
        self.usuario.setPlaceholderText("cuenta de PostgreSQL")
        self.clave = QgsPasswordLineEdit()
        formulario = QFormLayout()
        formulario.addRow("Usuario", self.usuario)
        formulario.addRow("Contraseña", self.clave)

        self.host = QLineEdit(ajustes.host)
        self.puerto_base = QSpinBox()
        self.puerto_base.setRange(1024, 65530)
        self.puerto_base.setValue(ajustes.puerto_base)
        self.puerto_base.setToolTip("El central usa este puerto y cada campus usa el puerto base + campus_id.")
        self.base_datos = QLineEdit(ajustes.base_datos)
        conexion = QgsCollapsibleGroupBox("Conexión")
        conexion.setCollapsed(True)
        formulario_conexion = QFormLayout(conexion)
        formulario_conexion.addRow("Servidor", self.host)
        formulario_conexion.addRow("Puerto base", self.puerto_base)
        formulario_conexion.addRow("Base de datos", self.base_datos)

        self.mensaje = QLabel()
        self.mensaje.setWordWrap(True)
        self.mensaje.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.mensaje.setStyleSheet("color: #b3261e;")
        self.mensaje.hide()

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botones.button(QDialogButtonBox.StandardButton.Ok).setText("Iniciar sesión")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)

        disposicion = QVBoxLayout(self)
        disposicion.addLayout(formulario)
        disposicion.addWidget(conexion)
        disposicion.addWidget(self.mensaje)
        disposicion.addWidget(botones)
        (self.clave if usuario else self.usuario).setFocus()

    def ajustes(self):
        return Ajustes(
            host=self.host.text().strip() or Ajustes.host,
            puerto_base=self.puerto_base.value(),
            base_datos=self.base_datos.text().strip() or Ajustes.base_datos,
        )

    def accept(self):
        self.mensaje.hide()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.resultado = self._al_aceptar(self.ajustes(), self.usuario.text(), self.clave.text())
        except ErrorSesion as error:
            self.mensaje.setText(str(error))
            self.mensaje.show()
            self.clave.selectAll()
            self.clave.setFocus()
            return
        except OperacionCancelada:
            self.cancelado = True
            self.reject()
            return
        finally:
            QApplication.restoreOverrideCursor()
        super().accept()

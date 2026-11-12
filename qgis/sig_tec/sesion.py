"""Inicio de sesión contra el central y carga de las vistas del campus en QGIS."""

from dataclasses import dataclass

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsAuthMethodConfig,
    QgsCoordinateReferenceSystem,
    QgsDataSourceUri,
    QgsFeatureRequest,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)

from .configuracion import (
    CAPAS,
    CLAVE_PRIMARIA,
    COLUMNA_GEOMETRIA,
    CONSULTA_CAMPUS,
    CREDENCIALES,
    ESQUEMA_VISTAS,
    SRID,
    ErrorSesion,
    clasificar_error_conexion,
    nombre_campus,
)

ESTILO_BASE_DATOS = "base de datos"
ESTILO_LOCAL = "archivo local"

# Marca las capas y grupos que agrega el complemento, aunque se muevan o dupliquen en el proyecto.
PROPIEDAD_USUARIO = "sig_tec/usuario"
PROPIEDAD_CAMPUS = "sig_tec/campus_id"

# Respuestas posibles cuando hay ediciones sin guardar en las capas que se van a retirar.
GUARDAR = "guardar"
DESCARTAR = "descartar"
CANCELAR = "cancelar"


class OperacionCancelada(Exception):
    """La persona usuaria canceló; el proyecto queda como estaba."""


@dataclass(frozen=True)
class Sesion:
    usuario: str
    campus_id: int
    authcfg: str

    @property
    def nombre_campus(self):
        return nombre_campus(self.campus_id)


@dataclass
class Carga:
    grupo: object
    capas: list
    estilos: dict


def _driver():
    # QGIS distribuye psycopg2 en Windows y lo usa DB Manager; psycopg 3 sirve como alternativa.
    try:
        import psycopg2 as driver
    except ImportError:
        try:
            import psycopg as driver
        except ImportError:
            raise ErrorSesion("El Python de QGIS no tiene psycopg2 ni psycopg. Instale uno de los dos.") from None
    return driver


def _detalle(error):
    lineas = [linea.strip() for linea in str(error).splitlines() if linea.strip()]
    return lineas[-1] if lineas else type(error).__name__


def _conectar(ajustes, puerto, usuario, clave):
    """Abre una conexión directa para validar credenciales sin el diálogo de credenciales de QGIS."""
    driver = _driver()
    conexion = driver.connect(
        host=ajustes.host,
        port=puerto,
        dbname=ajustes.base_datos,
        user=usuario,
        password=clave,
        connect_timeout=5,
        application_name="SIG-TEC QGIS",
    )
    return driver, conexion


def consultar_campus(ajustes, usuario, clave):
    """Valida la cuenta en el central y devuelve su campus_id."""
    driver = _driver()
    try:
        _, conexion = _conectar(ajustes, ajustes.puerto_central, usuario, clave)
    except driver.OperationalError as error:
        if clasificar_error_conexion(str(error)) == CREDENCIALES:
            raise ErrorSesion("Usuario o contraseña incorrectos.") from None
        raise ErrorSesion(
            f"El servidor central no está disponible en {ajustes.host}:{ajustes.puerto_central}. "
            f"Intente de nuevo cuando se restablezca.\n\nDetalle: {_detalle(error)}"
        ) from None

    try:
        cursor = conexion.cursor()
        cursor.execute(CONSULTA_CAMPUS)
        fila = cursor.fetchone()
    except driver.Error as error:
        raise ErrorSesion(f"El servidor central no pudo consultar el campus de la cuenta.\n\nDetalle: {_detalle(error)}") from None
    finally:
        conexion.close()

    campus_id = fila[0] if fila else None
    if campus_id is None:
        raise ErrorSesion("La cuenta no tiene un campus asignado en el servidor central.")
    campus_id = int(campus_id)
    try:
        ajustes.puerto_campus(campus_id)
    except ValueError:
        raise ErrorSesion(f"El servidor central asignó un campus desconocido ({campus_id}).") from None
    return campus_id


def verificar_nodo_campus(ajustes, campus_id, usuario, clave):
    """Comprueba que el nodo del campus responde y acepta la misma cuenta."""
    driver = _driver()
    puerto = ajustes.puerto_campus(campus_id)
    campus = nombre_campus(campus_id)
    try:
        _, conexion = _conectar(ajustes, puerto, usuario, clave)
    except driver.OperationalError as error:
        if clasificar_error_conexion(str(error)) == CREDENCIALES:
            raise ErrorSesion(
                f"El central validó la cuenta, pero el nodo de {campus} la rechazó. "
                "La cuenta debe existir con la misma contraseña en el central y en su campus."
            ) from None
        raise ErrorSesion(
            f"El nodo de {campus} no está disponible en {ajustes.host}:{puerto}.\n\nDetalle: {_detalle(error)}"
        ) from None
    conexion.close()


def guardar_credenciales(usuario, clave):
    """Guarda la cuenta en el gestor de autenticación de QGIS y devuelve el id de authcfg."""
    gestor = QgsApplication.authManager()
    if gestor.isDisabled():
        raise ErrorSesion(f"El sistema de autenticación de QGIS está deshabilitado: {gestor.disabledMessage()}")
    if not gestor.masterPasswordIsSet() and not gestor.setMasterPassword(True):
        raise ErrorSesion("Se necesita la contraseña maestra de QGIS para guardar las credenciales.")

    nombre = f"SIG-TEC {usuario}"
    existente = next(
        (cid for cid, cfg in gestor.availableAuthMethodConfigs().items() if cfg.name() == nombre),
        None,
    )
    config = QgsAuthMethodConfig("Basic")
    config.setName(nombre)
    config.setConfig("username", usuario)
    config.setConfig("password", clave)
    if existente:
        config.setId(existente)
        resultado = gestor.updateAuthenticationConfig(config)
    else:
        resultado = gestor.storeAuthenticationConfig(config)
    # Según la versión de los enlaces, el método devuelve bool o (bool, configuración).
    if isinstance(resultado, tuple):
        resultado, config = resultado[0], resultado[-1]
    if not resultado or not config.id():
        raise ErrorSesion("QGIS no pudo guardar las credenciales en su base de autenticación.")
    return config.id()


def iniciar_sesion(ajustes, usuario, clave):
    usuario = usuario.strip()
    if not usuario or not clave:
        raise ErrorSesion("Escriba el usuario y la contraseña.")
    campus_id = consultar_campus(ajustes, usuario, clave)
    verificar_nodo_campus(ajustes, campus_id, usuario, clave)
    return Sesion(usuario, campus_id, guardar_credenciales(usuario, clave))


def crear_capa(ajustes, sesion, capa):
    uri = QgsDataSourceUri()
    uri.setConnection(ajustes.host, str(ajustes.puerto_campus(sesion.campus_id)), ajustes.base_datos, "", "")
    uri.setAuthConfigId(sesion.authcfg)
    uri.setDataSource(ESQUEMA_VISTAS, capa.vista, COLUMNA_GEOMETRIA, "", CLAVE_PRIMARIA)
    uri.setSrid(str(SRID))
    uri.setWkbType(getattr(Qgis.WkbType, capa.geometria))
    return QgsVectorLayer(uri.uri(False), capa.titulo, "postgres")


def aplicar_estilo(capa_qgis, capa):
    """Usa el estilo compartido de public.layer_styles y, si falta, el QML incluido en el complemento."""
    if capa_qgis.listStylesInDatabase()[0] > 0:
        _, cargado = capa_qgis.loadDefaultStyle()
        if cargado:
            return ESTILO_BASE_DATOS
    if capa.archivo_estilo.exists():
        _, cargado = capa_qgis.loadNamedStyle(str(capa.archivo_estilo))
        if cargado:
            return ESTILO_LOCAL
    return None


def capas_de_sesion(proyecto):
    return [capa for capa in proyecto.mapLayers().values() if capa.customProperty(PROPIEDAD_USUARIO) is not None]


def capas_con_cambios(capas):
    return [capa for capa in capas if capa.isEditable() and capa.isModified()]


def retirar_capas(proyecto, decidir=None):
    """Retira todas las capas de SIG-TEC del proyecto y devuelve cuántas eran.

    Si alguna tiene ediciones sin guardar, `decidir(capas)` responde GUARDAR, DESCARTAR o CANCELAR.
    Sin `decidir`, se cancela. Al cancelar o si falla el guardado, no se retira ninguna capa.
    """
    capas = capas_de_sesion(proyecto)
    pendientes = capas_con_cambios(capas)
    if pendientes:
        decision = decidir(pendientes) if decidir else CANCELAR
        if decision == GUARDAR:
            fallidas = [capa for capa in pendientes if not capa.commitChanges()]
            if fallidas:
                detalle = "; ".join(f"{capa.name()}: {' '.join(capa.commitErrors()[-2:])}" for capa in fallidas)
                raise ErrorSesion(
                    "No se pudieron guardar las ediciones de "
                    + ", ".join(capa.name() for capa in fallidas)
                    + ". Las capas siguen en el proyecto con sus cambios pendientes.\n\nDetalle: "
                    + detalle
                )
        elif decision == DESCARTAR:
            for capa in pendientes:
                capa.rollBack()
        elif decision == CANCELAR:
            raise OperacionCancelada()
        else:
            raise ValueError(f"decisión desconocida: {decision}")

    for capa in capas:
        if capa.isEditable():
            capa.rollBack()
    proyecto.removeMapLayers([capa.id() for capa in capas])

    for grupo in proyecto.layerTreeRoot().findGroups(True):
        if grupo.customProperty(PROPIEDAD_USUARIO) is None:
            continue
        if grupo.children():
            # Conserva lo que la persona haya agregado dentro del grupo.
            grupo.removeCustomProperty(PROPIEDAD_USUARIO)
        else:
            grupo.parent().removeChildNode(grupo)
    return len(capas)


def cargar_capas(ajustes, sesion, proyecto=None, decidir=None):
    """Reemplaza la sesión anterior por las ocho vistas del campus de `sesion`.

    Política: el proyecto tiene una sola sesión de SIG-TEC. Antes de agregar las capas nuevas
    se retiran todas las anteriores, sin importar la cuenta o el campus (ver `retirar_capas`).
    Si alguna vista nueva no abre, o si se cancela, el proyecto no cambia.
    """
    proyecto = proyecto or QgsProject.instance()
    pares = [(capa, crear_capa(ajustes, sesion, capa)) for capa in CAPAS]
    invalidas = [capa.vista for capa, capa_qgis in pares if not capa_qgis.isValid()]
    if invalidas:
        raise ErrorSesion(
            f"No se pudieron abrir estas vistas en el nodo de {sesion.nombre_campus}: "
            + ", ".join(f"{ESQUEMA_VISTAS}.{vista}" for vista in invalidas)
        )

    retirar_capas(proyecto, decidir)
    if not proyecto.mapLayers():
        proyecto.setCrs(QgsCoordinateReferenceSystem(f"EPSG:{SRID}"))

    grupo = proyecto.layerTreeRoot().insertGroup(0, f"SIG-TEC · {sesion.nombre_campus}")
    estilos = {}
    for objeto in (grupo, *(capa_qgis for _, capa_qgis in pares)):
        objeto.setCustomProperty(PROPIEDAD_USUARIO, sesion.usuario)
        objeto.setCustomProperty(PROPIEDAD_CAMPUS, sesion.campus_id)
    for capa, capa_qgis in pares:
        estilos[capa.vista] = aplicar_estilo(capa_qgis, capa)
        proyecto.addMapLayer(capa_qgis, False)
        grupo.addLayer(capa_qgis)
    return Carga(grupo, [capa_qgis for _, capa_qgis in pares], estilos)


def extension_campus(capas, campus_id, margen=50):
    """Rectángulo que contiene los objetos del campus, en el SRID de las capas."""
    extension = QgsRectangle()
    solicitud = QgsFeatureRequest().setFilterExpression(f'"campus_id" = {int(campus_id)}')
    for capa_qgis in capas:
        for objeto in capa_qgis.getFeatures(solicitud):
            if not objeto.hasGeometry():
                continue
            caja = objeto.geometry().boundingBox()
            if extension.isNull():
                extension = caja
            else:
                extension.combineExtentWith(caja)
    if extension.isNull():
        return None
    extension.grow(margen)
    return extension

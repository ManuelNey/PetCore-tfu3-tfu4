"""
Pide el historial de una mascota al servicio SOAP (contenedor "historial-soap").

API -> consultar_historial, con el token del usuario.
Worker -> obtener_historial, para armar el PDF.

HistorialRechazado: pedido rechazado, con el código HTTP en estado.
HistorialNoDisponible: fallo temporal, se puede reintentar.
"""

import logging
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import jwt

from app.config import settings

logger = logging.getLogger(__name__)

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
HISTORIAL_NS = "urn:petcore:historial"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

# Tipos para pasar del texto XML a los datos que usa el PDF.
CAMPOS_BOOLEANOS = {"consistente", "recuperada", "edicion_vencida", "corregida", "vigente"}
CAMPOS_ENTEROS = {"id", "id_consulta", "recuperadas", "esperadas", "total"}
CAMPOS_DECIMALES = {"peso_actual"}
CAMPOS_FECHA = {"fecha", "fecha_nacimiento", "corregida_el"}
CAMPOS_FECHA_HORA = {"modificada_el", "ultimo_intento"}
CAMPOS_LISTA = {"advertencias", "consultas", "correcciones"}


class HistorialNoDisponible(Exception):
    """No se pudo obtener el historial por un problema temporal (se puede reintentar)."""


class HistorialRechazado(LookupError):
    """El servicio SOAP rechazó la solicitud. `estado` es el código HTTP (400, 401, 403, 404...)."""

    def __init__(self, estado: int, mensaje: str) -> None:
        super().__init__(mensaje)
        self.estado = estado


# --- Pedido ---

def _crear_token(id_veterinario: int) -> str:
    """
    El worker crea un token corto a nombre del veterinario, con la clave de la API.
    SOAP lo valida como los demás tokens.
    """
    ahora = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(id_veterinario),
            "rol": "VETERINARIO",
            "type": "access",
            "iss": "pet-core-api",
            "aud": "pet-core-client",
            "iat": ahora,
            "nbf": ahora,
            "exp": ahora + timedelta(minutes=2),
            "jti": str(uuid4()),
        },
        settings.JWT_SECRET_KEY,
        algorithm="HS256",
    )


def _crear_mensaje(
    id_mascota: int,
    limite: int | None = None,
    offset: int | None = None,
    tipo: str | None = None,
) -> bytes:
    """Mensaje SOAP/XML de la operación ObtenerHistorialMascota."""
    parametros = f"<h:id_mascota>{int(id_mascota)}</h:id_mascota>"
    if limite is not None:
        parametros += f"<h:limite>{int(limite)}</h:limite>"
    if offset is not None:
        parametros += f"<h:offset>{int(offset)}</h:offset>"
    if tipo is not None:
        parametros += f"<h:tipo>{escape(tipo)}</h:tipo>"

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<soap:Envelope xmlns:soap="{SOAP_NS}" xmlns:h="{HISTORIAL_NS}">'
        "<soap:Body>"
        f"<h:ObtenerHistorialMascota>{parametros}</h:ObtenerHistorialMascota>"
        "</soap:Body>"
        "</soap:Envelope>"
    ).encode("utf-8")


# --- Respuesta ---

def _nombre(elemento) -> str:
    """Nombre de la etiqueta sin el espacio de nombres."""
    return elemento.tag.rpartition("}")[2]


def _convertir_texto(nombre: str, texto: str):
    try:
        if nombre in CAMPOS_BOOLEANOS:
            return texto == "true"
        if nombre in CAMPOS_ENTEROS:
            return int(texto)
        if nombre in CAMPOS_DECIMALES:
            return float(texto)
        if nombre in CAMPOS_FECHA:
            return date.fromisoformat(texto)
        if nombre in CAMPOS_FECHA_HORA:
            return datetime.fromisoformat(texto)
    except ValueError:
        pass
    return texto


def _a_python(elemento):
    """Convierte un elemento XML en dict, lista, valor simple o None."""
    nombre = _nombre(elemento)

    if elemento.get(f"{{{XSI_NS}}}nil") in ("true", "1"):
        return None

    if nombre in CAMPOS_LISTA:
        return [_a_python(hijo) for hijo in elemento]

    if len(elemento) > 0:
        return {_nombre(hijo): _a_python(hijo) for hijo in elemento}

    return _convertir_texto(nombre, elemento.text or "")


def _leer_historial(contenido: bytes) -> dict:
    """Lee el historial del XML, según la vista que haya devuelto SOAP."""
    cuerpo = ET.fromstring(contenido).find(f"{{{SOAP_NS}}}Body")
    if cuerpo is None or len(cuerpo) != 1:
        raise ValueError("La respuesta SOAP no tiene el formato esperado.")

    respuesta = cuerpo[0]
    for vista in ("veterinario", "cliente"):
        datos = respuesta.find(f"{{{HISTORIAL_NS}}}{vista}")
        if datos is not None:
            return _a_python(datos)

    raise ValueError("La respuesta SOAP no trae el historial.")


def _leer_error(contenido: bytes) -> tuple[int, str] | None:
    """Si el XML es un SOAP Fault, devuelve (código HTTP original, mensaje)."""
    try:
        fallo = ET.fromstring(contenido).find(f"{{{SOAP_NS}}}Body/{{{SOAP_NS}}}Fault")
    except ET.ParseError:
        return None
    if fallo is None:
        return None

    mensaje = fallo.findtext("faultstring") or "El servicio de historial rechazó la solicitud."
    try:
        estado = int(fallo.findtext("detail/status") or 500)
    except ValueError:
        estado = 500
    return estado, mensaje


# --- Llamada ---

def obtener_historial(id_mascota: int, id_veterinario: int) -> dict:
    """Historial del veterinario para armar el PDF. El token lo arma el worker."""
    return consultar_historial(_crear_token(id_veterinario), id_mascota)


def consultar_historial(
    token: str,
    id_mascota: int,
    limite: int | None = None,
    offset: int | None = None,
    tipo: str | None = None,
) -> dict:
    """Llama a ObtenerHistorialMascota con el token dado y devuelve el historial."""
    pedido = urllib.request.Request(
        settings.SOAP_HISTORIAL_URL,
        data=_crear_mensaje(id_mascota, limite, offset, tipo),
        method="POST",
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"{HISTORIAL_NS}/ObtenerHistorialMascota"',
            "Authorization": f"Bearer {token}",
        },
    )

    try:
        with urllib.request.urlopen(pedido, timeout=settings.SOAP_TIMEOUT_SEGUNDOS) as respuesta:
            contenido = respuesta.read()

    except urllib.error.HTTPError as error:
        # El servicio SOAP responde los errores con un SOAP Fault (HTTP 500).
        fallo = _leer_error(error.read())
        if fallo is not None and fallo[0] < 500:
            # 400, 401, 403, 404...: reintentar no lo arregla.
            raise HistorialRechazado(fallo[0], fallo[1]) from error
        raise HistorialNoDisponible(f"El servicio de historial respondió con error {error.code}.") from error

    except (urllib.error.URLError, OSError) as error:
        # Servicio caído, sin red o demasiado lento (incluye timeouts).
        raise HistorialNoDisponible("No se pudo comunicar con el servicio de historial.") from error

    try:
        return _leer_historial(contenido)
    except (ET.ParseError, ValueError) as error:
        logger.error("Respuesta SOAP inválida: %s", error)
        raise HistorialNoDisponible("El servicio de historial devolvió una respuesta inválida.") from error

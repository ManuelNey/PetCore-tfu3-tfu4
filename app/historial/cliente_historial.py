"""
Pide el historial de una mascota para que el worker arme el PDF.

La función obtener_historial(id_mascota, id_veterinario) devuelve los datos del
historial con el mismo formato que ya usa el generador del PDF (pdf.py).

Si algo sale mal, avisa con uno de dos errores, y el worker decide qué hacer:
- LookupError: el problema no se arregla solo (por ejemplo, la mascota no existe).
  El worker no vuelve a intentarlo.
- HistorialNoDisponible: el problema es pasajero (por ejemplo, la base no responde).
  El worker lo vuelve a intentar más tarde.
"""

import logging

from psycopg import OperationalError
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError

from app.database import abrir_sesion_con_reintentos
from app.historial.repository import HistorialRepository
from app.historial.service import HistorialService

logger = logging.getLogger(__name__)


class HistorialNoDisponible(Exception):
    """No se pudo obtener el historial por un problema temporal (se puede reintentar)."""


# PROVISORIO: este cuerpo de función es lo único que tiene que reemplazar la persona
# que hace el servicio SOAP. Hoy llama directo a HistorialService (misma base, sin red).
# Cuando exista la operación SOAP ObtenerHistorialMascota, hay que:
#   1. Reemplazar TODO el cuerpo por una llamada al servicio SOAP (cliente del WSDL),
#      mandando id_mascota e id_veterinario (y el token/credencial que defina esa persona).
#   2. Convertir la respuesta XML a un dict con la MISMA forma del contrato de arriba
#      (fechas como date/str, listas anidadas "correcciones", flags "recuperada"...).
#   3. Mapear los SOAP Faults: "mascota no encontrada" -> LookupError;
#      servicio caído, timeout o error de red -> HistorialNoDisponible.
# El worker, RabbitMQ y la API no se tocan.
def obtener_historial(id_mascota: int, id_veterinario: int) -> dict:
    try:
        session = abrir_sesion_con_reintentos()
    except (OperationalError, SQLAlchemyOperationalError) as error:
        raise HistorialNoDisponible("No se pudo conectar a la base.") from error

    try:
        repositorio = HistorialRepository(session)

        # Se chequea antes porque HistorialService, ante una mascota inexistente, intenta
        # auditar con ese id y revienta con IntegrityError (clave foránea) en vez de LookupError.
        if repositorio.obtener_info_mascota(id_mascota) is None:
            raise LookupError("Mascota no encontrada.")

        return HistorialService(repositorio).obtener_historial_veterinario(
            id_mascota, id_veterinario, None
        )
    except (OperationalError, SQLAlchemyOperationalError) as error:
        session.rollback()
        raise HistorialNoDisponible("Falló la consulta del historial.") from error
    finally:
        session.close()

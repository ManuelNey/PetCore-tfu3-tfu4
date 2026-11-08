"""
Reenvía los pedidos que quedaron guardados sin publicar en RabbitMQ.
Corre en un hilo de la API (ver main.py).
"""

import logging
import threading
import time

from psycopg import OperationalError
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError

from app.config import settings
from app.database import abrir_sesion_con_reintentos
from app.historial.exportacion_repository import ExportacionRepository
from app.mensajeria import eventos, rabbitmq

logger = logging.getLogger(__name__)

# Máximo de tareas por vuelta.
TAREAS_POR_VUELTA = 20


def reenviar_pendientes() -> int:
    """Publica los eventos pendientes y devuelve cuántos se enviaron."""
    session = abrir_sesion_con_reintentos()
    enviados = 0

    try:
        repositorio = ExportacionRepository(session)
        pendientes = repositorio.bloquear_eventos_sin_publicar(
            settings.OUTBOX_ANTIGUEDAD_SEGUNDOS, TAREAS_POR_VUELTA
        )

        for tarea in pendientes:
            try:
                rabbitmq.publicar(
                    eventos.RK_SOLICITADA,
                    eventos.exportacion_solicitada(
                        str(tarea["id_tarea"]), tarea["id_mascota"], tarea["id_usuario"]
                    ),
                    tiempo_maximo=3.0,
                )
            except rabbitmq.ErrorMensajeria:
                # RabbitMQ sigue sin responder: se prueba en la próxima vuelta.
                logger.warning("Reenvío: RabbitMQ no responde, se reintenta más tarde.")
                break

            repositorio.marcar_evento_publicado_sin_commit(tarea["id_tarea"])
            enviados += 1
            logger.info("Reenvío: evento de la tarea %s publicado.", tarea["id_tarea"])

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return enviados


def _bucle() -> None:
    while True:
        try:
            reenviar_pendientes()
        except (OperationalError, SQLAlchemyOperationalError):
            logger.warning("Reenvío: la base no responde, se reintenta más tarde.")
        except Exception:
            logger.exception("Reenvío: error inesperado.")
        time.sleep(settings.OUTBOX_INTERVALO_SEGUNDOS)


def iniciar_reenviador() -> threading.Thread:
    """Arranca el reenviador en un hilo que se cierra junto con la API."""
    hilo = threading.Thread(target=_bucle, name="reenviador-eventos", daemon=True)
    hilo.start()
    return hilo

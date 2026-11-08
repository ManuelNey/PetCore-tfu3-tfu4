"""
Recibe los resultados que manda el worker y actualiza el estado de cada tarea.

Corre en un hilo de la API (ver main.py). Si hay dos replicas, cada resultado
lo toma una sola; las dos usan la misma base.

- ExportacionGenerada -> la tarea pasa a LISTO.
- ExportacionFallida  -> la tarea pasa a ERROR (salvo que ya esté LISTO).
"""

import json
import logging
import threading
import time
from uuid import UUID

from pika.exceptions import AMQPError
from psycopg import OperationalError
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError

from app.database import abrir_sesion_con_reintentos
from app.historial.exportacion_repository import ExportacionRepository
from app.mensajeria import eventos, rabbitmq

logger = logging.getLogger(__name__)


def aplicar_resultado(datos: dict) -> None:
    """
    Actualiza la tarea. Repetir el resultado deja el mismo estado.
    Un mensaje inválido lanza ValueError, KeyError o TypeError.
    """
    evento = datos["evento"]
    id_tarea = UUID(datos["id_tarea"])

    session = abrir_sesion_con_reintentos()
    try:
        repositorio = ExportacionRepository(session)

        if evento == "ExportacionGenerada":
            # El PDF siempre se llama igual que la tarea; si no coincide, algo anda mal.
            archivo = datos["archivo"]
            if archivo != f"{id_tarea}.pdf":
                raise ValueError("El nombre del archivo no corresponde a la tarea.")
            repositorio.marcar_listo(id_tarea, archivo)
        elif evento == "ExportacionFallida":
            repositorio.marcar_error(id_tarea, str(datos["motivo"]))
        else:
            raise ValueError(f"Evento desconocido: {evento}")
    finally:
        session.close()


def _al_recibir(canal, metodo, _propiedades, cuerpo: bytes) -> None:
    try:
        aplicar_resultado(json.loads(cuerpo))
    except (ValueError, KeyError, TypeError) as error:
        # Mensaje inválido: reintentarlo no sirve, se descarta.
        logger.error("Resultado inválido, se descarta: %s", error)
        canal.basic_nack(metodo.delivery_tag, requeue=False)
        return
    except (OperationalError, SQLAlchemyOperationalError):
        # La base no responde: el resultado vuelve a la cola para no perderlo.
        logger.warning("No se pudo guardar el resultado (base caída), se reencola.")
        time.sleep(2)
        canal.basic_nack(metodo.delivery_tag, requeue=True)
        return

    canal.basic_ack(metodo.delivery_tag)


def consumir_resultados() -> None:
    """Bucle que escucha los resultados. Si se corta la conexión, reconecta."""
    while True:
        try:
            _conexion, canal = rabbitmq.abrir_canal()
            canal.basic_qos(prefetch_count=1)
            canal.basic_consume(eventos.COLA_RESULTADOS, on_message_callback=_al_recibir)
            logger.info("Escuchando resultados de exportación.")
            canal.start_consuming()
        except (AMQPError, OSError) as error:
            logger.warning("Sin conexión con RabbitMQ (%s). Reintentando en 5s...", error)
            time.sleep(5)


def iniciar_consumidor() -> threading.Thread:
    """Arranca el consumidor en un hilo que se cierra junto con la API."""
    hilo = threading.Thread(target=consumir_resultados, name="consumidor-resultados", daemon=True)
    hilo.start()
    return hilo

"""
Worker de exportaciones: un programa aparte de la API que arma los PDF del historial.

Cada vez que llega una solicitud de exportación (ExportacionSolicitada), hace esto:
1. Si el PDF de esa tarea ya existe (la solicitud llegó repetida), no lo arma de nuevo:
   solo avisa otra vez que está listo.
2. Pide el historial. Si falla por algo pasajero, lo vuelve a intentar unas veces.
3. Arma el PDF y lo guarda en la carpeta compartida.
4. Avisa el resultado (ExportacionGenerada si salió bien, ExportacionFallida si no)
   y recién después da la solicitud por atendida. Si el worker se cae antes de
   hacerlo, RabbitMQ le vuelve a mandar la solicitud.

Se ejecuta con:  python -m app.worker.main
"""

import json
import logging
import os
import time
from pathlib import Path
from uuid import UUID

from pika.exceptions import AMQPError

from app.config import settings
from app.historial.cliente_historial import HistorialNoDisponible, obtener_historial
from app.historial.pdf import generar_pdf_historial
from app.mensajeria import eventos, rabbitmq

logger = logging.getLogger("worker")


def procesar_solicitud(id_tarea: str, id_mascota: int, id_veterinario: int) -> tuple[str, dict]:
    """
    Resuelve una solicitud y devuelve (routing_key, evento) con el resultado.
    Nunca lanza errores de negocio: los convierte en ExportacionFallida para que
    ninguna tarea quede pendiente para siempre.
    """
    nombre_archivo = f"{id_tarea}.pdf"
    destino = Path(settings.EXPORTACIONES_DIR) / nombre_archivo

    # Solicitud repetida: el PDF ya está, no se hace nada de nuevo.
    if destino.is_file():
        logger.info("Tarea %s ya estaba generada (solicitud repetida).", id_tarea)
        return eventos.RK_GENERADA, eventos.exportacion_generada(id_tarea, nombre_archivo)

    # Pausa solo para la demo (permite ver la tarea PENDIENTE o detener el worker). En un uso real es 0.
    time.sleep(settings.EXPORTACION_RETARDO_SEGUNDOS)

    historial = None
    for intento in range(1, settings.WORKER_INTENTOS_HISTORIAL + 1):
        try:
            historial = obtener_historial(id_mascota, id_veterinario)
            break
        except LookupError as error:
            # Error que no se arregla reintentando.
            logger.warning("Tarea %s: %s", id_tarea, error)
            return eventos.RK_FALLIDA, eventos.exportacion_fallida(id_tarea, str(error))
        except HistorialNoDisponible as error:
            logger.warning(
                "Tarea %s: historial no disponible (intento %d/%d): %s",
                id_tarea, intento, settings.WORKER_INTENTOS_HISTORIAL, error,
            )
            if intento < settings.WORKER_INTENTOS_HISTORIAL:
                time.sleep(settings.WORKER_ESPERA_BASE_SEGUNDOS * 2 ** (intento - 1))

    if historial is None:
        return eventos.RK_FALLIDA, eventos.exportacion_fallida(
            id_tarea, "El historial no está disponible. Se agotaron los intentos."
        )

    try:
        # Se escribe en un archivo temporal y después se renombra: así nunca queda
        # un PDF a medio escribir con el nombre definitivo (que contaría como "ya generado").
        temporal = destino.with_suffix(".pdf.tmp")
        generar_pdf_historial(historial, temporal)
        os.replace(temporal, destino)
    except Exception:
        logger.exception("Tarea %s: no se pudo generar el PDF.", id_tarea)
        return eventos.RK_FALLIDA, eventos.exportacion_fallida(id_tarea, "No se pudo generar el PDF.")

    logger.info("Tarea %s: PDF generado.", id_tarea)
    return eventos.RK_GENERADA, eventos.exportacion_generada(id_tarea, nombre_archivo)


def al_recibir(canal, metodo, _propiedades, cuerpo: bytes) -> None:
    """Se ejecuta por cada mensaje de la cola de solicitudes."""
    try:
        datos = json.loads(cuerpo)
        id_tarea = str(UUID(datos["id_tarea"]))
        id_mascota = int(datos["id_mascota"])
        id_veterinario = int(datos["id_veterinario"])
    except (ValueError, KeyError, TypeError) as error:
        # Mensaje mal formado: reintentarlo no sirve. Va a la cola de mensajes muertos.
        logger.error("Mensaje inválido, se descarta a la cola de muertos: %s", error)
        canal.basic_nack(metodo.delivery_tag, requeue=False)
        return

    routing_key, resultado = procesar_solicitud(id_tarea, id_mascota, id_veterinario)

    try:
        rabbitmq.publicar(routing_key, resultado)
    except rabbitmq.ErrorMensajeria:
        # No se pudo avisar el resultado: la solicitud vuelve a la cola para reintentar.
        # Como el PDF ya existe, repetirla es barato.
        logger.error("Tarea %s: no se pudo publicar el resultado, se reencola.", id_tarea)
        time.sleep(2)
        canal.basic_nack(metodo.delivery_tag, requeue=True)
        return

    canal.basic_ack(metodo.delivery_tag)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logger.info("Worker iniciado. Esperando solicitudes...")

    while True:
        try:
            conexion, canal = rabbitmq.abrir_canal()
            # De a una solicitud por vez: las demás esperan en la cola (Queue-Based Load Leveling).
            canal.basic_qos(prefetch_count=1)
            canal.basic_consume(eventos.COLA_SOLICITADAS, on_message_callback=al_recibir)
            canal.start_consuming()
        except KeyboardInterrupt:
            logger.info("Worker detenido.")
            break
        except (AMQPError, OSError) as error:
            # RabbitMQ no disponible o conexión perdida: se espera y se reconecta.
            logger.warning("Sin conexión con RabbitMQ (%s). Reintentando en 5s...", error)
            time.sleep(5)


if __name__ == "__main__":
    main()

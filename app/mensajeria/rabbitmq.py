"""
Conexión con RabbitMQ: crea las colas, publica eventos y abre canales para recibirlos.
"""

import json
import logging
import time

import pika
from pika.exceptions import AMQPError

from app.config import settings
from app.mensajeria import eventos

logger = logging.getLogger(__name__)


class ErrorMensajeria(Exception):
    """No se pudo publicar el evento después de todos los intentos."""


def _parametros() -> pika.ConnectionParameters:
    return pika.ConnectionParameters(
        host=settings.RABBITMQ_HOST,
        port=settings.RABBITMQ_PORT,
        credentials=pika.PlainCredentials(settings.RABBITMQ_USER, settings.RABBITMQ_PASSWORD),
        heartbeat=60,
        # Si RabbitMQ no responde, cortamos rapido este intento.
        connection_attempts=1,
        socket_timeout=2,
        stack_timeout=2,
        blocked_connection_timeout=10,
    )


def declarar_topologia(canal) -> None:
    """
    Crea las colas y exchanges que falten. API y worker pueden llamarlo al arrancar.
    """
    canal.exchange_declare(eventos.EXCHANGE, exchange_type="direct", durable=True)
    canal.exchange_declare(eventos.EXCHANGE_MUERTOS, exchange_type="direct", durable=True)

    # Cola de mensajes que el worker rechazó sin reencolar.
    canal.queue_declare(eventos.COLA_MUERTOS, durable=True)
    canal.queue_bind(
        eventos.COLA_MUERTOS, eventos.EXCHANGE_MUERTOS, routing_key=eventos.COLA_SOLICITADAS
    )

    # Solicitudes para el worker. Si las rechaza van a la cola de muertos
    canal.queue_declare(
        eventos.COLA_SOLICITADAS,
        durable=True,
        arguments={
            "x-dead-letter-exchange": eventos.EXCHANGE_MUERTOS,
            "x-dead-letter-routing-key": eventos.COLA_SOLICITADAS,
        },
    )
    canal.queue_bind(eventos.COLA_SOLICITADAS, eventos.EXCHANGE, routing_key=eventos.RK_SOLICITADA)

    # Resultados para la API
    canal.queue_declare(eventos.COLA_RESULTADOS, durable=True)
    canal.queue_bind(eventos.COLA_RESULTADOS, eventos.EXCHANGE, routing_key=eventos.RK_GENERADA)
    canal.queue_bind(eventos.COLA_RESULTADOS, eventos.EXCHANGE, routing_key=eventos.RK_FALLIDA)


def abrir_canal():
    """
    Devuelve (conexion, canal), con las colas listas. Quien llama cierra la conexión.
    """
    conexion = pika.BlockingConnection(_parametros())
    canal = conexion.channel()
    declarar_topologia(canal)
    return conexion, canal


def publicar(routing_key: str, evento: dict, tiempo_maximo: float | None = None) -> None:
    """
    Publica un mensaje persistente y espera la confirmación de RabbitMQ.
    Si falla, reintenta hasta RABBITMQ_INTENTOS, con esperas de 0.5s, 1s, ...
    tiempo_maximo evita empezar otro intento si no queda tiempo para la espera.
    Si no pudo enviarlo, lanza ErrorMensajeria.
    """
    cuerpo = json.dumps(evento, ensure_ascii=False).encode("utf-8")
    ultimo_error: Exception | None = None
    total_intentos = settings.RABBITMQ_INTENTOS
    inicio = time.monotonic()
    intentos_hechos = 0

    for intento in range(1, total_intentos + 1):
        intentos_hechos = intento
        conexion = None
        try:
            conexion = pika.BlockingConnection(_parametros())
            canal = conexion.channel()
            declarar_topologia(canal)
            canal.confirm_delivery()
            canal.basic_publish(
                exchange=eventos.EXCHANGE,
                routing_key=routing_key,
                body=cuerpo,
                properties=pika.BasicProperties(
                    delivery_mode=pika.DeliveryMode.Persistent,
                    content_type="application/json",
                ),
                mandatory=True,
            )
            logger.info("EVENTO PUBLICADO: %s (%s)", evento.get("evento"), evento.get("id_tarea"))
            return
        except (AMQPError, OSError) as error:
            ultimo_error = error
            logger.warning(
                "Falló la publicación de %s (intento %d/%d): %s",
                evento.get("evento"), intento, total_intentos, error,
            )
            espera = 0.5 * 2 ** (intento - 1)
            sin_tiempo = (
                tiempo_maximo is not None
                and time.monotonic() - inicio + espera >= tiempo_maximo
            )
            if intento == total_intentos or sin_tiempo:
                break
            time.sleep(espera)
        finally:
            if conexion is not None and conexion.is_open:
                conexion.close()

    raise ErrorMensajeria(
        f"No se pudo publicar {evento.get('evento')} tras {intentos_hechos} intentos."
    ) from ultimo_error

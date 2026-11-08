"""
Acceso a RabbitMQ para publicar y consumir eventos.

Garantías que se buscan (por qué se hace así):
- Colas y exchanges DURABLES: sobreviven a un reinicio de RabbitMQ.
- Mensajes PERSISTENTES (delivery_mode=2): se escriben a disco.
- Confirmación de publicación (publisher confirms) + mandatory: si RabbitMQ no
  confirma o el mensaje no llega a ninguna cola, `publicar` lo sabe y falla en
  vez de perder el evento en silencio.
- RETRY con espera creciente al conectar/publicar: la red no es confiable.
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
        # Si RabbitMQ no responde, cada intento se rinde rápido (no esperar decenas de segundos).
        connection_attempts=1,
        socket_timeout=2,
        stack_timeout=2,
        blocked_connection_timeout=10,
    )


def declarar_topologia(canal) -> None:
    """
    Crea exchanges y colas si no existen. Es idempotente: se puede llamar
    desde la API y desde el worker sin importar quién arranque primero.
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
    Abre conexión y canal con la topología lista. Lo usan los consumidores
    (worker y API). Quien lo llama debe cerrar la conexión.
    Devuelve (conexion, canal).
    """
    conexion = pika.BlockingConnection(_parametros())
    canal = conexion.channel()
    declarar_topologia(canal)
    return conexion, canal


def publicar(routing_key: str, evento: dict, tiempo_maximo: float | None = None) -> None:
    """
    Publica un evento con mensaje persistente y confirmación de RabbitMQ.
    Reintenta si falla la conexión o no hay confirmación (espera 0.5s, 1s, etc),
    hasta RABBITMQ_INTENTOS veces.
    `tiempo_maximo` (segundos) limita el tiempo total: si ya se gastó, no empieza otro
    intento. Sirve cuando hay una persona esperando la respuesta (la API).
    Si no logra publicar lanza ErrorMensajeria.
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

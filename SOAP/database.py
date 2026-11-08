import logging
import time
from collections.abc import Generator

from psycopg import OperationalError
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError
from sqlmodel import Session, create_engine, text

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(
    str(settings.SQLALCHEMY_DATABASE_URI),
    # Sin esto, si el host de Postgres no responde (contenedor caído), el intento de
    # conexión puede tardar varios segundos en fallar (timeout de TCP del SO) en vez de
    # fallar rápido. Eso rompía /health: a veces dos réplicas lentas en fila superaban
    # el timeout de Nginx y devolvía 504 en vez de un 503 limpio.
    connect_args={"connect_timeout": 2},
)

# Activado solo para forzar la falla desde afuera en una demo.
FALLAR_PROXIMAS_CONEXIONES = {"cantidad": 0}

# Datos del último intento de conexión, para poder consultarlos en la demo
# (ver GET /debug/ultimo-intento-conexion).
ULTIMO_INTENTO_CONEXION = {
    "intentos_usados": 0,
    "duracion_segundos": 0.0,
    "exitoso": True,
}


def abrir_sesion_con_reintentos(intentos: int = 3, espera_base: float = 0.5) -> Session:
    """
    Abre una sesión contra la base, reintentando con backoff exponencial si
    la conexión falla por algo transitorio (red, Postgres reiniciando, etc).
    """
    inicio = time.monotonic()

    for intento in range(1, intentos + 1):
        try:
            if FALLAR_PROXIMAS_CONEXIONES["cantidad"] > 0:
                FALLAR_PROXIMAS_CONEXIONES["cantidad"] -= 1
                raise OperationalError("Falla simulada para la demo")

            session = Session(engine)
            # Esta línea es la que realmente prueba la conexión. Sin ella,
            # Session(engine) no falla hasta la primera query real del service.
            session.execute(text("SELECT 1"))

            ULTIMO_INTENTO_CONEXION["intentos_usados"] = intento
            ULTIMO_INTENTO_CONEXION["duracion_segundos"] = round(
                time.monotonic() - inicio, 3
            )
            ULTIMO_INTENTO_CONEXION["exitoso"] = True

            return session

        except (OperationalError, SQLAlchemyOperationalError) as error:
            if intento == intentos:
                ULTIMO_INTENTO_CONEXION["intentos_usados"] = intento
                ULTIMO_INTENTO_CONEXION["duracion_segundos"] = round(
                    time.monotonic() - inicio, 3
                )
                ULTIMO_INTENTO_CONEXION["exitoso"] = False

                logger.error("No se pudo conectar tras %s intentos.", intentos)
                raise

            espera = espera_base * (2 ** (intento - 1))
            logger.warning(
                "Intento %s/%s falló (%s). Reintentando en %ss...",
                intento, intentos, error, espera,
            )
            time.sleep(espera)


def get_session() -> Generator[Session, None, None]:
    session = abrir_sesion_con_reintentos()
    try:
        yield session
    finally:
        session.close()

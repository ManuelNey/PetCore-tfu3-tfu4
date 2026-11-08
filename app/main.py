import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from psycopg import OperationalError
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError
from sqlmodel import Session, text
from app.database import FALLAR_PROXIMAS_CONEXIONES, ULTIMO_INTENTO_CONEXION, engine, get_session
from app.configuracion.controller import router as configuracion_router

from app.turnos.repository import FORZAR_FALLA_TRAS_INSERTAR_CONSULTA
from app.Middleware.middleware import JWTMiddleware, obtener_usuario_actual
from app.turnos.tareas_programadas import ejecutar_tarea_periodica
from app.Auth.login.controller import router as login_router
from app.Auth.me.controller import router as me_router
from app.Auth.Register.clients.controller import router as register_client_router
from app.Mascotas.controller import router as mascotas_router
from app.tipos_atencion.controller import (
    router as tipos_atencion_router,
)
from app.veterinarios.controller import router as veterinarios_router
from app.turnos.controller import router as turnos_router
from app.especies.controller import router as especies_router
from app.disponibilidad.controller import router as disponibilidad_router
from app.agenda.controller import router as agenda_router
from app.historial.controller import router as historial_router
from app.pacientes.controller import router as pacientes_router
from app.demo.controller import router as demo_router
from app.historial.consumidor_resultados import iniciar_consumidor
from app.historial.reenviador_eventos import iniciar_reenviador


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Marca turnos vencidos como NO_ASISTIO en segundo plano mientras la API esté activa.
    tarea = asyncio.create_task(ejecutar_tarea_periodica())

    # Recibe por RabbitMQ los resultados del worker.
    iniciar_consumidor()

    # Reenvía los pedidos que quedaron sin publicar.
    iniciar_reenviador()

    yield

    tarea.cancel()


app = FastAPI(
    title="Pet-Core API",
    lifespan=lifespan,
)

# Permite que el frontend (Vite, en desarrollo) llame a la API desde el navegador.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(JWTMiddleware)

app.include_router(login_router)
app.include_router(register_client_router)
app.include_router(me_router)
app.include_router(tipos_atencion_router)
app.include_router(mascotas_router)
app.include_router(veterinarios_router)
app.include_router(turnos_router)
app.include_router(especies_router)
app.include_router(disponibilidad_router)
app.include_router(agenda_router)
app.include_router(historial_router)
app.include_router(pacientes_router)
app.include_router(demo_router)
app.include_router(configuracion_router)

@app.get("/")
def hello():
    return "Hello, Docker!"

#Verifica que la API esté funcionando correctamente, incluyendo la conexión a la base.
#Si la base no responde, devuelve 503 para que Docker/Nginx dejen de mandarle tráfico
#a esta réplica (ver healthcheck del servicio "server" en compose.yaml).
#Chequea la conexión directo (sin los reintentos de get_session): un health check
#debe fallar rápido, no demorarse reintentando con backoff.
@app.get("/health")
def health() -> dict:
    try:
        with Session(engine) as session:
            session.execute(text("SELECT 1"))
    except (OperationalError, SQLAlchemyOperationalError):
        raise HTTPException(status_code=503, detail="Base de datos no disponible.")
    return {"status": "ok"}

# Solo para demostrar los reintentos de conexión a la base (ver app/database.py).
@app.post("/debug/simular-falla-conexion")
def simular_falla_conexion(
    veces: int = 2,
    _usuario: dict = Depends(obtener_usuario_actual),
) -> dict:
    FALLAR_PROXIMAS_CONEXIONES["cantidad"] = veces
    return {"mensaje": f"Las próximas {veces} conexiones van a fallar"}

# Datos del último intento de conexión a la base (ver app/database.py).
@app.get("/debug/ultimo-intento-conexion")
def ultimo_intento_conexion(
    _usuario: dict = Depends(obtener_usuario_actual),
) -> dict:
    return ULTIMO_INTENTO_CONEXION

# Solo para demostrar ACID: arma la próxima llamada a
# POST /turnos/{id_turno}/consulta para que falle justo después de
# insertar la consulta clínica y antes de actualizar el turno y hacer
# commit (ver TurnoRepository.registrar_consulta).
@app.post("/debug/simular-falla-registrar-consulta")
def simular_falla_registrar_consulta(
    _usuario: dict = Depends(obtener_usuario_actual),
) -> dict:
    FORZAR_FALLA_TRAS_INSERTAR_CONSULTA["activar"] = True
    return {
        "mensaje": (
            "La próxima llamada a POST /turnos/{id_turno}/consulta va a "
            "fallar a mitad de camino"
        )
    }


# Estado actual de un turno + cuántas consultas clínicas tiene registradas.
# Se usa antes y después de la falla simulada para comprobar que no quedó
# nada a medias (ver README-TFU3.md, sección 4).
@app.get("/debug/estado-turno/{id_turno}")
def estado_turno_debug(
    id_turno: int,
    _usuario: dict = Depends(obtener_usuario_actual),
    session: Session = Depends(get_session),
) -> dict:
    turno = session.execute(
        text("SELECT estado FROM turno WHERE id_turno = :id_turno"),
        {"id_turno": id_turno},
    ).mappings().first()

    if turno is None:
        raise HTTPException(status_code=404, detail="Turno no encontrado.")

    total_consultas = session.execute(
        text("SELECT count(*) AS total FROM consulta_clinica WHERE id_turno = :id_turno"),
        {"id_turno": id_turno},
    ).scalar_one()

    return {
        "id_turno": id_turno,
        "estado_turno": turno["estado"],
        "consultas_clinicas_registradas": total_consultas,
    }

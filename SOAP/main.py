import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import engine
from app.Middleware.middleware import JWTMiddleware
from app.distribuido.soap_service import router as historial_soap_router


logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Pet-Core — Servicio SOAP de historial",
)

# Esta aplicación tiene su propio proceso.
# Registra el mismo middleware utilizado por la API original.
app.add_middleware(JWTMiddleware)

app.include_router(historial_soap_router)


@app.get("/health")
def comprobar_salud():
    """Comprueba que la aplicación puede consultar PostgreSQL."""
    try:
        with Session(engine) as session:
            session.execute(text("SELECT 1"))

    except SQLAlchemyError:
        logger.warning(
            "La comprobación de salud no pudo consultar PostgreSQL."
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "detail": "Base de datos no disponible.",
            },
        )

    return {"status": "ok"}
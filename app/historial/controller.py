from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_session
from app.historial.dto import (
    ExportacionEstadoResponse,
    ExportacionIniciadaResponse,
    HistorialClienteResponse,
    HistorialVeterinarioResponse,
)
from app.historial.exportacion_repository import ExportacionRepository
from app.historial.exportacion_service import (
    ExportacionNoEncolada,
    ExportacionService,
    TareaNoLista,
)
from app.historial.repository import HistorialRepository
from app.historial.service import HistorialService
from app.historial.valet_key import ValetKeyInvalida, ValetKeyNoCorresponde
from app.Middleware.middleware import obtener_usuario_actual, requerir_rol

router = APIRouter(tags=["Historial"])


def crear_service(session: Session) -> HistorialService:
    return HistorialService(HistorialRepository(session))


def crear_exportacion_service(session: Session) -> ExportacionService:
    return ExportacionService(ExportacionRepository(session), HistorialRepository(session))


@router.get(
    "/mascotas/{id_mascota}/historial",
    response_model=HistorialClienteResponse | HistorialVeterinarioResponse,
)
def ver_historial(
    id_mascota: int,
    limite: int = 10,
    offset: int = 0,
    tipo: str | None = None,
    usuario: dict[str, Any] = Depends(obtener_usuario_actual),
    session: Session = Depends(get_session),
):
    service = crear_service(session)

    try:
        if usuario["rol"] == "VETERINARIO":
            return service.obtener_historial_veterinario(id_mascota, usuario["id_usuario"], tipo)

        if usuario["rol"] == "CLIENTE":
            return service.obtener_historial_cliente(
                id_mascota, usuario["id_usuario"], limite, offset
            )

        # ADMINISTRADOR u otro rol: sin acceso al contenido clínico.
        HistorialRepository(session).registrar_acceso(
            usuario["id_usuario"], id_mascota, usuario["rol"], "RECHAZADO",
            "Rol sin acceso al historial clinico.",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Rol sin acceso a este recurso.",
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

# --- Exportación del historial a PDF (Asynchronous Request-Reply) ---

@router.post(
    "/historial/{id_mascota}/exportar",
    response_model=ExportacionIniciadaResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def iniciar_exportacion(
    id_mascota: int,
    usuario: dict[str, Any] = Depends(requerir_rol("VETERINARIO")),
    session: Session = Depends(get_session),
):
    """Crea la tarea, manda la solicitud al worker y responde enseguida (202). El PDF se prepara después."""
    service = crear_exportacion_service(session)

    try:
        id_tarea = service.iniciar(id_mascota, usuario["id_usuario"])
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ExportacionNoEncolada as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo enviar la solicitud de exportación. Intente de nuevo en unos instantes.",
        ) from error

    return {"id_tarea": id_tarea, "estado": "PENDIENTE"}


@router.get("/historial/exportar/{id_tarea}", response_model=ExportacionEstadoResponse)
def estado_exportacion(
    id_tarea: UUID,
    usuario: dict[str, Any] = Depends(requerir_rol("VETERINARIO")),
    session: Session = Depends(get_session),
):
    """Dice si la exportación está PENDIENTE, LISTO o ERROR."""
    service = crear_exportacion_service(session)

    try:
        tarea = service.consultar(id_tarea, usuario["id_usuario"])
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return {
        "id_tarea": tarea["id_tarea"],
        "estado": tarea["estado"],
        "fecha_creacion": tarea["fecha_creacion"],
        "enlace_descarga": service.enlace_descarga(tarea),
        "error": tarea["detalle_error"],
    }


# --- Descarga con Valet Key ---

@router.get("/historial/exportar/{id_tarea}/descargar")
def descargar_exportacion(
    id_tarea: UUID,
    token: str = Query(..., description="Valet Key recibido en enlace_descarga."),
    session: Session = Depends(get_session),
):
    """Descarga el PDF con el enlace del Valet Key. No hace falta iniciar sesión."""
    service = crear_exportacion_service(session)

    try:
        ruta = service.archivo_para_descarga(id_tarea, token)
    except ValetKeyInvalida as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except ValetKeyNoCorresponde as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except TareaNoLista as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    return FileResponse(ruta, media_type="application/pdf", filename=f"historial-{id_tarea}.pdf")

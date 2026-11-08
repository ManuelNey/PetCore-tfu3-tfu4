import logging
from xml.etree.ElementTree import ParseError

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import get_session
from app.Middleware.middleware import obtener_usuario_actual
from app.historial.repository import HistorialRepository
from app.historial.service import HistorialService
from app.historial.dto import (
    HistorialClienteResponse,
    HistorialVeterinarioResponse,
)
from app.distribuido.soap_xml import (
    HISTORIAL_NS,
    XSI_NS,
    agregar_dato,
    convertir_a_xml,
    crear_error,
    crear_sobre,
    generar_wsdl,
    leer_operacion,
)


logger = logging.getLogger(__name__)

MAX_XML_BYTES = 2_000_000


class RutaSOAP(APIRoute):
    """Convierte los errores de las rutas SOAP en mensajes XML."""

    def get_route_handler(self):
        """Envuelve el procesamiento normal de FastAPI."""
        manejador_original = super().get_route_handler()

        async def manejar(request: Request):
            """Ejecuta la ruta y transforma sus errores en SOAP Fault."""
            try:
                return await manejador_original(request)

            except StarletteHTTPException as error:
                return Response(
                    content=crear_error(
                        str(error.detail),
                        error.status_code,
                    ),
                    status_code=500,
                    media_type="text/xml",
                    headers=error.headers,
                )

            except RequestValidationError:
                return Response(
                    content=crear_error(
                        "Los parámetros de la solicitud no son válidos.",
                        400,
                    ),
                    status_code=500,
                    media_type="text/xml",
                )

            except Exception:
                logger.exception(
                    "Error interno consultando el historial por SOAP."
                )

                return Response(
                    content=crear_error(
                        "El servicio de historial no está disponible.",
                        503,
                    ),
                    status_code=500,
                    media_type="text/xml",
                )

        return manejar


router = APIRouter(
    prefix="/soap",
    tags=["Historial SOAP"],
    route_class=RutaSOAP,
)


class ConsultaHistorialSOAP(BaseModel):
    """Valida los parámetros recibidos mediante XML."""

    id_mascota: int = Field(gt=0)
    limite: int = Field(default=10, ge=0)
    offset: int = Field(default=0, ge=0)
    tipo: str | None = None


async def leer_cuerpo_xml(request: Request) -> bytes:
    """Lee la solicitud limitando su tamaño durante la recepción."""
    fragmentos = []
    total = 0

    async for fragmento in request.stream():
        total += len(fragmento)

        if total > MAX_XML_BYTES:
            raise HTTPException(
                status_code=413,
                detail="El mensaje SOAP es demasiado grande.",
            )

        fragmentos.append(fragmento)

    return b"".join(fragmentos)


@router.get("/historial", include_in_schema=False)
def obtener_wsdl(request: Request):
    """Publica el contrato WSDL sin consultar información clínica."""
    if "wsdl" not in request.query_params:
        raise HTTPException(
            status_code=400,
            detail="Para obtener el contrato agregá ?wsdl a la dirección.",
        )

    # Usa la dirección con la que el consumidor llegó al servicio.
    # Desde Windows será localhost:8001.
    # Desde Docker será historial-soap:8001.
    direccion_servicio = str(
        request.url.replace(query="")
    )

    return Response(
        content=generar_wsdl(direccion_servicio),
        media_type="text/xml",
    )


@router.post("/historial")
async def consultar_historial(
    request: Request,
    usuario: dict = Depends(obtener_usuario_actual),
    session: Session = Depends(get_session),
):
    """Consulta el historial permitido para el usuario autenticado."""

    # 1. Leer y validar el mensaje SOAP.
    contenido = await leer_cuerpo_xml(request)

    try:
        operacion = leer_operacion(contenido)

        operacion_esperada = (
            f"{{{HISTORIAL_NS}}}ObtenerHistorialMascota"
        )

        if operacion.tag != operacion_esperada:
            raise ValueError("Operación SOAP desconocida.")

        parametros = {}

        for campo in operacion:
            prefijo = f"{{{HISTORIAL_NS}}}"

            if not campo.tag.startswith(prefijo):
                raise ValueError(
                    "El parámetro tiene un espacio de nombres incorrecto."
                )

            nombre = campo.tag.removeprefix(prefijo)

            if nombre not in ConsultaHistorialSOAP.model_fields:
                raise ValueError("Parámetro desconocido.")

            if nombre in parametros:
                raise ValueError("Parámetro repetido.")

            if len(campo) > 0:
                raise ValueError(
                    "El parámetro debe contener un valor simple."
                )

            es_nulo = (
                campo.get(f"{{{XSI_NS}}}nil")
                in ("true", "1")
            )

            parametros[nombre] = (
                None if es_nulo else campo.text
            )

        consulta = ConsultaHistorialSOAP.model_validate(
            parametros
        )

    except (ParseError, ValueError) as error:
        raise HTTPException(
            status_code=400,
            detail="La solicitud SOAP no es válida.",
        ) from error

    # 2. Reutilizar las reglas y consultas del historial.
    repository = HistorialRepository(session)
    service = HistorialService(repository)

    try:
        if usuario["rol"] == "VETERINARIO":
            resultado = service.obtener_historial_veterinario(
                consulta.id_mascota,
                usuario["id_usuario"],
                consulta.tipo,
            )

            datos = (
                HistorialVeterinarioResponse
                .model_validate(resultado)
                .model_dump(mode="json")
            )

            nombre_respuesta = "veterinario"

        elif usuario["rol"] == "CLIENTE":
            resultado = service.obtener_historial_cliente(
                consulta.id_mascota,
                usuario["id_usuario"],
                consulta.limite,
                consulta.offset,
            )

            datos = (
                HistorialClienteResponse
                .model_validate(resultado)
                .model_dump(mode="json")
            )

            nombre_respuesta = "cliente"

        else:
            repository.registrar_acceso(
                usuario["id_usuario"],
                consulta.id_mascota,
                usuario["rol"],
                "RECHAZADO",
                "Rol sin acceso al historial clínico.",
            )

            raise HTTPException(
                status_code=403,
                detail="Rol sin acceso al historial clínico.",
            )

    except LookupError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    # 3. Construir la respuesta SOAP/XML.
    sobre, respuesta = crear_sobre(
        "ObtenerHistorialMascotaResponse"
    )

    agregar_dato(
        respuesta,
        nombre_respuesta,
        datos,
    )

    return Response(
        content=convertir_a_xml(sobre),
        media_type="text/xml",
    )
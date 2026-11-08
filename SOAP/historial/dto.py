from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# --- Respuesta para CLIENTE ---

class ConsultaClienteItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_consulta: int
    fecha: date
    hora: str
    tipo: str
    veterinario: str
    motivo: str
    diagnostico: str
    observaciones: str | None
    tratamiento: str | None
    recomendaciones: str | None
    modificada_el: datetime | None
    edicion_vencida: bool
    corregida: bool
    corregida_el: date | None


class HistorialClienteResponse(BaseModel):
    total: int
    consultas: list[ConsultaClienteItem]


# --- Respuesta para VETERINARIO ---

class MascotaHistorialInfo(BaseModel):
    id: int
    nombre: str
    especie: str
    raza: str | None
    fecha_nacimiento: date | None
    peso_actual: float | None
    propietario: str
    telefono: str


class CorreccionItem(BaseModel):
    id: int
    fecha: date
    hora: str
    veterinario: str
    motivo_correccion: str
    # Campos clínicos que la corrección haya modificado (motivo, diagnostico,
    # observaciones, tratamiento o recomendaciones) — los incluyo todos por
    # simplicidad; el frontend muestra los que tengan valor.
    diagnostico: str | None = None
    observaciones: str | None = None
    tratamiento: str | None = None
    recomendaciones: str | None = None
    vigente: bool


class ConsultaRecuperada(BaseModel):
    id: int
    recuperada: bool = True
    fecha: date
    hora: str
    tipo: str
    veterinario: str
    motivo: str
    observaciones: str | None
    diagnostico: str
    tratamiento: str | None
    recomendaciones: str | None
    modificada_el: datetime | None
    edicion_vencida: bool
    corregida: bool
    corregida_el: date | None
    correcciones: list[CorreccionItem]


class ConsultaNoRecuperada(BaseModel):
    id: None = None
    recuperada: bool = False
    mensaje: str = (
        "Consulta no recuperada. Existe en el registro pero no se pudo "
        "leer su contenido."
    )


class HistorialVeterinarioResponse(BaseModel):
    mascota: MascotaHistorialInfo
    consistente: bool
    recuperadas: int
    esperadas: int
    ultimo_intento: datetime
    advertencias: list[str]
    consultas: list[ConsultaRecuperada | ConsultaNoRecuperada]

# --- Exportación a PDF (Asynchronous Request-Reply) ---

class ExportacionIniciadaResponse(BaseModel):
    id_tarea: UUID
    estado: str


class ExportacionEstadoResponse(BaseModel):
    id_tarea: UUID
    estado: str
    fecha_creacion: datetime
    # Solo cuando está LISTO: el enlace para descargar el PDF.
    enlace_descarga: str | None = None
    # Solo cuando está en ERROR.
    error: str | None = None

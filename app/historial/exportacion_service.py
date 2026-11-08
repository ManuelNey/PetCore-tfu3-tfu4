import logging
from pathlib import Path
from uuid import UUID

from app.config import settings
from app.historial.exportacion_repository import ExportacionRepository
from app.historial.repository import HistorialRepository
from app.historial.valet_key import generar_valet_key, validar_valet_key
from app.mensajeria import eventos, rabbitmq

logger = logging.getLogger(__name__)


class TareaNoLista(Exception):
    """La tarea existe, pero el PDF todavía no está listo"""


def ruta_archivo(nombre_archivo: str) -> Path | None:
    """Devuelve dónde está guardado el PDF, o None si no existe."""
    ruta = Path(settings.EXPORTACIONES_DIR) / nombre_archivo
    return ruta if ruta.is_file() else None


class ExportacionService:
    def __init__(
        self,
        exportaciones: ExportacionRepository,
        historial: HistorialRepository,
    ) -> None:
        self.exportaciones = exportaciones
        self.historial = historial

    def iniciar(self, id_mascota: int, id_veterinario: int) -> UUID:
        """
        Valida la mascota, guarda la tarea y manda ExportacionSolicitada al worker.
        Si RabbitMQ no responde, queda pendiente para el reenviador.
        """
        if not self.historial.obtener_info_mascota(id_mascota):
            raise LookupError("Mascota no encontrada.")

        id_tarea = self.exportaciones.crear_tarea(id_mascota, id_veterinario)

        try:
            # Limitamos la espera porque Nginx corta a los 5 segundos.
            rabbitmq.publicar(
                eventos.RK_SOLICITADA,
                eventos.exportacion_solicitada(str(id_tarea), id_mascota, id_veterinario),
                tiempo_maximo=3.0,
            )
            self.exportaciones.marcar_evento_publicado(id_tarea)
        except rabbitmq.ErrorMensajeria:
            logger.warning("Tarea %s: RabbitMQ no respondió, el evento se enviará después.", id_tarea)

        return id_tarea

    def consultar(self, id_tarea: UUID, id_veterinario: int) -> dict:
        tarea = self.exportaciones.obtener_tarea(id_tarea)

        # Si la tarea es de otro veterinario, respondemos como si no existiera.
        if tarea is None or tarea["id_usuario"] != id_veterinario:
            raise LookupError("Tarea de exportación no encontrada.")

        return tarea

    def enlace_descarga(self, tarea: dict) -> str | None:
        """Crea el enlace con el Valet Key, solo si el PDF ya está listo."""
        if tarea["estado"] != "LISTO" or ruta_archivo(tarea["archivo"]) is None:
            return None

        token = generar_valet_key(tarea["id_tarea"])
        return f"/historial/exportar/{tarea['id_tarea']}/descargar?token={token}"

    def archivo_para_descarga(self, id_tarea: UUID, token: str) -> Path:
        """Revisa el Valet Key y devuelve el PDF."""
        validar_valet_key(token, id_tarea)

        tarea = self.exportaciones.obtener_tarea(id_tarea)
        if tarea is None:
            raise LookupError("Tarea de exportación no encontrada.")
        if tarea["estado"] != "LISTO":
            raise TareaNoLista("El PDF todavía no está disponible.")

        ruta = ruta_archivo(tarea["archivo"])
        if ruta is None:
            raise LookupError("El archivo ya no está disponible.")

        return ruta

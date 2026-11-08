"""
Contrato de eventos de la exportación del historial (arquitectura basada en eventos).

Flujo:
    API  --ExportacionSolicitada-->  Worker
    API  <--ExportacionGenerada----  Worker
    API  <--ExportacionFallida-----  Worker

Todos los eventos llevan `id_tarea`, que identifica la exportación a la que pertenecen.
"""

# --- RabbitMQ: exchange y colas ---

EXCHANGE = "petcore.exportaciones"

# Mensajes rechazados sin reencolar: quedan acá para revisarlos.
EXCHANGE_MUERTOS = "petcore.exportaciones.muertos"
COLA_MUERTOS = "exportaciones.solicitadas.muertas"

# Cola que consume el worker.
COLA_SOLICITADAS = "exportaciones.solicitadas"
RK_SOLICITADA = "exportacion.solicitada"

# Cola que consume la API para actualizar el estado de la tarea.
COLA_RESULTADOS = "exportaciones.resultados"
RK_GENERADA = "exportacion.generada"
RK_FALLIDA = "exportacion.fallida"


# --- Constructores de eventos (JSON) ---

def exportacion_solicitada(id_tarea: str, id_mascota: int, id_veterinario: int) -> dict:
    return {
        "evento": "ExportacionSolicitada",
        "id_tarea": id_tarea,
        "id_mascota": id_mascota,
        "id_veterinario": id_veterinario,
    }


def exportacion_generada(id_tarea: str, archivo: str) -> dict:
    # Nombre del PDF en la carpeta compartida.
    return {
        "evento": "ExportacionGenerada",
        "id_tarea": id_tarea,
        "archivo": archivo,
    }


def exportacion_fallida(id_tarea: str, motivo: str) -> dict:
    return {
        "evento": "ExportacionFallida",
        "id_tarea": id_tarea,
        "motivo": motivo,
    }

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


class ExportacionRepository:
    """Consultas a la tabla tarea_exportacion (donde se guarda el estado de cada exportación)."""

    def __init__(self, session: Session) -> None:
        self.session: Session = session

    def crear_tarea(self, id_mascota: int, id_usuario: int) -> UUID:
        consulta = text(
            """
            INSERT INTO tarea_exportacion (id_mascota, id_usuario)
            VALUES (:id_mascota, :id_usuario)
            RETURNING id_tarea
            """
        )
        id_tarea = self.session.execute(
            consulta, {"id_mascota": id_mascota, "id_usuario": id_usuario}
        ).scalar_one()
        self.session.commit()
        return id_tarea

    def obtener_tarea(self, id_tarea: UUID) -> dict | None:
        consulta = text(
            """
            SELECT id_tarea, id_mascota, id_usuario, estado, archivo,
                   detalle_error, fecha_creacion
            FROM tarea_exportacion
            WHERE id_tarea = :id_tarea
            """
        )
        fila = self.session.execute(consulta, {"id_tarea": id_tarea}).mappings().first()
        return dict(fila) if fila else None

    def marcar_listo(self, id_tarea: UUID, archivo: str) -> None:
        consulta = text(
            "UPDATE tarea_exportacion SET estado = 'LISTO', archivo = :archivo WHERE id_tarea = :id_tarea"
        )
        self.session.execute(consulta, {"id_tarea": id_tarea, "archivo": archivo})
        self.session.commit()

    def marcar_error(self, id_tarea: UUID, detalle: str) -> None:
        # Una tarea LISTO no se pisa con un error: si el PDF existe, es lo que vale.
        consulta = text(
            """
            UPDATE tarea_exportacion SET estado = 'ERROR', detalle_error = :detalle
            WHERE id_tarea = :id_tarea AND estado <> 'LISTO'
            """
        )
        self.session.execute(consulta, {"id_tarea": id_tarea, "detalle": detalle})
        self.session.commit()

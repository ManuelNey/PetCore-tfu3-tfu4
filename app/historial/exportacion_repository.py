from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


class ExportacionRepository:
    """Guarda y consulta las tareas de exportación."""

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

    def marcar_evento_publicado(self, id_tarea: UUID) -> None:
        """Anota que el evento de la tarea ya se publicó en RabbitMQ."""
        consulta = text(
            "UPDATE tarea_exportacion SET evento_publicado = TRUE WHERE id_tarea = :id_tarea"
        )
        self.session.execute(consulta, {"id_tarea": id_tarea})
        self.session.commit()

    def bloquear_eventos_sin_publicar(self, antiguedad_segundos: int, limite: int) -> list[dict]:
        """
        Toma eventos sin publicar de tareas PENDIENTE con al menos antiguedad_segundos.
        La espera evita cruzarse con el pedido original. El bloqueo hasta el commit
        evita que dos réplicas reenvíen la misma tarea a la vez.
        """
        consulta = text(
            """
            SELECT id_tarea, id_mascota, id_usuario
            FROM tarea_exportacion
            WHERE estado = 'PENDIENTE'
              AND evento_publicado = FALSE
              AND fecha_creacion < now() - make_interval(secs => :antiguedad)
            ORDER BY fecha_creacion
            LIMIT :limite
            FOR UPDATE SKIP LOCKED
            """
        )
        filas = self.session.execute(
            consulta, {"antiguedad": antiguedad_segundos, "limite": limite}
        ).mappings().all()
        return [dict(fila) for fila in filas]

    def marcar_evento_publicado_sin_commit(self, id_tarea: UUID) -> None:
        """Igual que marcar_evento_publicado, pero el commit lo hace quien llama."""
        consulta = text(
            "UPDATE tarea_exportacion SET evento_publicado = TRUE WHERE id_tarea = :id_tarea"
        )
        self.session.execute(consulta, {"id_tarea": id_tarea})

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

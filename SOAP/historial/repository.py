from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session


class HistorialRepository:
    def __init__(self, session: Session) -> None:
        self.session: Session = session

    # --- Común ---

    def obtener_info_mascota(self, id_mascota: int) -> dict | None:
        consulta = text(
            """
            SELECT
                m.id_mascota AS id, m.nombre, m.especie, m.raza, m.fecha_nacimiento,
                (SELECT rp.peso FROM registro_peso rp
                 WHERE rp.id_mascota = m.id_mascota
                 ORDER BY rp.fecha_registro DESC LIMIT 1) AS peso_actual,
                u.nombre || ' ' || u.apellido AS propietario,
                u.telefono
            FROM mascota m
            JOIN usuario u ON u.id_usuario = m.id_cliente
            WHERE m.id_mascota = :id_mascota
            """
        )
        fila = self.session.execute(consulta, {"id_mascota": id_mascota}).mappings().first()
        return dict(fila) if fila else None

    def mascota_pertenece_a_cliente(self, id_mascota: int, id_cliente: int) -> bool:
        consulta = text(
            "SELECT 1 FROM mascota WHERE id_mascota = :id_mascota AND id_cliente = :id_cliente"
        )
        fila = self.session.execute(
            consulta, {"id_mascota": id_mascota, "id_cliente": id_cliente}
        ).first()
        return fila is not None

    # --- Cliente ---

    def contar_consultas_cliente(self, id_mascota: int) -> int:
        consulta = text(
            """
            SELECT COUNT(*) FROM consulta_clinica
            WHERE id_mascota = :id_mascota AND id_consulta_original IS NULL
            """
        )
        return self.session.execute(consulta, {"id_mascota": id_mascota}).scalar_one()

    def listar_consultas_cliente(self, id_mascota: int, limite: int, offset: int) -> list:
        consulta = text(
            """
            SELECT
                cc.id_consulta, cc.fecha_registro::date AS fecha,
                to_char(cc.fecha_registro, 'HH24:MI') AS hora,
                ta.nombre AS tipo,
                u.nombre || ' ' || u.apellido AS veterinario,
                cc.motivo, cc.diagnostico, cc.observaciones,
                cc.tratamiento, cc.recomendaciones,
                cc.fecha_modificacion AS modificada_el,
                (now() > cc.fecha_registro + interval '24 hours') AS edicion_vencida,
                EXISTS (
                    SELECT 1 FROM consulta_clinica cor
                    WHERE cor.id_consulta_original = cc.id_consulta
                ) AS corregida,
                (SELECT MAX(cor.fecha_registro)::date FROM consulta_clinica cor
                 WHERE cor.id_consulta_original = cc.id_consulta) AS corregida_el
            FROM consulta_clinica cc
            JOIN turno t ON t.id_turno = cc.id_turno
            JOIN tipo_atencion ta ON ta.id_tipo_atencion = t.id_tipo_atencion
            JOIN usuario u ON u.id_usuario = cc.id_veterinario
            WHERE cc.id_mascota = :id_mascota AND cc.id_consulta_original IS NULL
            ORDER BY cc.fecha_registro DESC
            LIMIT :limite OFFSET :offset
            """
        )
        return self.session.execute(
            consulta, {"id_mascota": id_mascota, "limite": limite, "offset": offset}
        ).mappings().all()

    # --- Veterinario ---

    def ids_esperados(self, id_mascota: int, tipo: str | None) -> set[int]:
        condicion_tipo = "AND ta.nombre = :tipo" if tipo else ""
        consulta = text(
            f"""
            SELECT cc.id_consulta
            FROM consulta_clinica cc
            JOIN turno t ON t.id_turno = cc.id_turno
            JOIN tipo_atencion ta ON ta.id_tipo_atencion = t.id_tipo_atencion
            WHERE cc.id_mascota = :id_mascota AND cc.id_consulta_original IS NULL
            {condicion_tipo}
            """
        )
        parametros = {"id_mascota": id_mascota}
        if tipo:
            parametros["tipo"] = tipo
        filas = self.session.execute(consulta, parametros).mappings().all()
        return {f["id_consulta"] for f in filas}

    def listar_originales_recuperadas(self, id_mascota: int, tipo: str | None) -> list:
        condicion_tipo = "AND ta.nombre = :tipo" if tipo else ""
        consulta = text(
            f"""
            SELECT
                cc.id_consulta, cc.fecha_registro::date AS fecha,
                to_char(cc.fecha_registro, 'HH24:MI') AS hora,
                ta.nombre AS tipo,
                u.nombre || ' ' || u.apellido AS veterinario,
                cc.motivo, cc.observaciones, cc.diagnostico,
                cc.tratamiento, cc.recomendaciones,
                cc.fecha_modificacion AS modificada_el,
                (now() > cc.fecha_registro + interval '24 hours') AS edicion_vencida
            FROM consulta_clinica cc
            JOIN turno t ON t.id_turno = cc.id_turno
            JOIN tipo_atencion ta ON ta.id_tipo_atencion = t.id_tipo_atencion
            JOIN usuario u ON u.id_usuario = cc.id_veterinario
            WHERE cc.id_mascota = :id_mascota AND cc.id_consulta_original IS NULL
            {condicion_tipo}
            ORDER BY cc.fecha_registro DESC
            """
        )
        parametros = {"id_mascota": id_mascota}
        if tipo:
            parametros["tipo"] = tipo
        return self.session.execute(consulta, parametros).mappings().all()

    def listar_correcciones(self, id_mascota: int) -> list:
        consulta = text(
            """
            SELECT
                cor.id_consulta AS id, cor.id_consulta_original,
                cor.fecha_registro::date AS fecha,
                to_char(cor.fecha_registro, 'HH24:MI') AS hora,
                u.nombre || ' ' || u.apellido AS veterinario,
                cor.motivo AS motivo_correccion,
                cor.diagnostico, cor.observaciones, cor.tratamiento, cor.recomendaciones
            FROM consulta_clinica cor
            JOIN usuario u ON u.id_usuario = cor.id_veterinario
            WHERE cor.id_mascota = :id_mascota AND cor.id_consulta_original IS NOT NULL
            ORDER BY cor.fecha_registro ASC
            """
        )
        return self.session.execute(consulta, {"id_mascota": id_mascota}).mappings().all()

    def registrar_acceso(
        self,
        id_usuario: int,
        id_mascota: int,
        rol: str,
        resultado: str,
        motivo_rechazo: str | None = None,
    ) -> None:
        consulta = text(
            """
            INSERT INTO acceso_historial (
                id_usuario, id_mascota, rol_utilizado, operacion, resultado, motivo_rechazo
            )
            VALUES (
                :id_usuario, :id_mascota, :rol, 'LECTURA', :resultado, :motivo_rechazo
            )
            """
        )
        self.session.execute(
            consulta,
            {
                "id_usuario": id_usuario,
                "id_mascota": id_mascota,
                "rol": rol,
                "resultado": resultado,
                "motivo_rechazo": motivo_rechazo,
            },
        )
        self.session.commit()
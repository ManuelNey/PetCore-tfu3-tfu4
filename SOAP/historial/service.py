from datetime import datetime, timezone

from app.historial.repository import HistorialRepository


class HistorialService:
    
    def __init__(self, repository: HistorialRepository) -> None:
        self.repository: HistorialRepository = repository

    # --- Cliente ---

    def obtener_historial_cliente(
        self, id_mascota: int, id_cliente: int, limite: int, offset: int
    ) -> dict:
        if not self.repository.mascota_pertenece_a_cliente(id_mascota, id_cliente):
            self.repository.registrar_acceso(
                id_cliente, id_mascota, "CLIENTE", "RECHAZADO",
                "La mascota no pertenece al cliente autenticado.",
            )
            raise LookupError("Mascota no encontrada.")

        total = self.repository.contar_consultas_cliente(id_mascota)
        filas = self.repository.listar_consultas_cliente(id_mascota, limite, offset)

        self.repository.registrar_acceso(id_cliente, id_mascota, "CLIENTE", "PERMITIDO")

        return {"total": total, "consultas": [dict(f) for f in filas]}

    # --- Veterinario ---

    def obtener_historial_veterinario(
        self, id_mascota: int, id_veterinario: int, tipo: str | None
    ) -> dict:
        info_mascota = self.repository.obtener_info_mascota(id_mascota)
        if not info_mascota:
            self.repository.registrar_acceso(
                id_veterinario, id_mascota, "VETERINARIO", "RECHAZADO",
                "Mascota no encontrada.",
            )
            raise LookupError("Mascota no encontrada.")

        ids_esperados = self.repository.ids_esperados(id_mascota, tipo)
        originales = self.repository.listar_originales_recuperadas(id_mascota, tipo)
        correcciones_filas = self.repository.listar_correcciones(id_mascota)

        correcciones_por_original: dict[int, list[dict]] = {}
        for c in correcciones_filas:
            correcciones_por_original.setdefault(c["id_consulta_original"], []).append(dict(c))

        for lista in correcciones_por_original.values():
            for c in lista:
                c["vigente"] = False
            lista[-1]["vigente"] = True

        ids_recuperados = {f["id_consulta"] for f in originales}
        ids_faltantes = ids_esperados - ids_recuperados

        consultas: list[dict] = []
        for fila in originales:
            item = dict(fila)
            id_consulta = item["id_consulta"]
            item["id"] = id_consulta
            item["recuperada"] = True
            item["corregida"] = id_consulta in correcciones_por_original
            correcciones = correcciones_por_original.get(id_consulta, [])
            item["corregida_el"] = correcciones[-1]["fecha"] if correcciones else None
            item["correcciones"] = correcciones
            consultas.append(item)

        for _ in ids_faltantes:
            consultas.append({"id": None, "recuperada": False})

        recuperadas = len(originales)
        esperadas = len(ids_esperados)
        consistente = recuperadas == esperadas

        advertencias = []
        if not consistente:
            faltan = esperadas - recuperadas
            advertencias.append(f"No se pudieron recuperar {faltan} de {esperadas} consultas.")

        self.repository.registrar_acceso(id_veterinario, id_mascota, "VETERINARIO", "PERMITIDO")

        return {
            "mascota": info_mascota,
            "consistente": consistente,
            "recuperadas": recuperadas,
            "esperadas": esperadas,
            "ultimo_intento": datetime.now(timezone.utc),
            "advertencias": advertencias,
            "consultas": consultas,
        }
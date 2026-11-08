-- Outbox: marca si se publicó el evento de la tarea.
-- FALSE -> falta publicar; la API lo reenvía.
-- TRUE  -> ya se publicó.
-- Las tareas anteriores quedan en TRUE para no reenviarlas.
-- Se puede ejecutar otra vez sin problemas.

BEGIN;

ALTER TABLE tarea_exportacion
    ADD COLUMN IF NOT EXISTS evento_publicado BOOLEAN NOT NULL DEFAULT TRUE;

-- Las tareas nuevas arrancan sin publicar.
ALTER TABLE tarea_exportacion
    ALTER COLUMN evento_publicado SET DEFAULT FALSE;

COMMIT;


-- ============================================
-- Si tu base ya existía, Postgres no ejecuta este archivo solo.
-- Para aplicarlo a mano:
--
--   Get-Content .\db\init\07_outbox_exportacion.sql -Raw | docker exec -i postgres-dev psql -U postgres -d postgres
-- ============================================

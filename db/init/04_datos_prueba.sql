-- ============================================
-- PET-CORE — Datos de prueba (solo desarrollo)
-- ============================================
--
-- Carga usuarios, mascotas, disponibilidad y un turno de ejemplo
-- para poder probar el login y el resto de los endpoints sin tener
-- que dar de alta todo a mano.
--
-- La contraseña de TODOS los usuarios de prueba es: contraSegura123
-- (el hash de abajo es bcrypt real, generado con pwdlib/BcryptHasher).
--
-- Se ejecuta después de 01_schema.sql, 02_permisos.sql y
-- 03_excepcion_disponibilidad.sql. Solo corre en una inicialización
-- limpia del volumen de Postgres (docker-entrypoint-initdb.d).
-- ============================================

BEGIN;

-- ============================================
-- ESPECIES
-- ============================================

INSERT INTO especie (nombre) VALUES
    ('Canino'),
    ('Felino'),
    ('Ave'),
    ('Roedor'),
    ('Reptil'),
    ('Otro');


-- ============================================
-- USUARIOS
-- ============================================

INSERT INTO usuario
    (nombre, apellido, documento, correo, telefono, contrasena_hash)
VALUES
    ('Ana', 'Gómez', '11111111', 'ana.cliente@petcore.com', '099111111',
        '$2b$12$WzUkssAmlTcpyYci2oBb5e.ufv.wuJpJ07pI4aGDg0hbGMjRemC8a'),
    ('Bruno', 'Pérez', '22222222', 'bruno.vet@petcore.com', '099222222',
        '$2b$12$WzUkssAmlTcpyYci2oBb5e.ufv.wuJpJ07pI4aGDg0hbGMjRemC8a'),
    ('Carla', 'Díaz', '33333333', 'carla.admin@petcore.com', '099333333',
        '$2b$12$WzUkssAmlTcpyYci2oBb5e.ufv.wuJpJ07pI4aGDg0hbGMjRemC8a');

-- Especialización de cada usuario según su rol.
INSERT INTO cliente (id_usuario)
    SELECT id_usuario FROM usuario WHERE correo = 'ana.cliente@petcore.com';

INSERT INTO veterinario (id_usuario, matricula_profesional)
    SELECT id_usuario, 'MP-1234'
    FROM usuario WHERE correo = 'bruno.vet@petcore.com';

INSERT INTO administrador (id_usuario)
    SELECT id_usuario FROM usuario WHERE correo = 'carla.admin@petcore.com';


-- ============================================
-- MASCOTAS (de la clienta Ana)
-- ============================================

INSERT INTO mascota
    (id_cliente, nombre, especie, raza, fecha_nacimiento, sexo)
SELECT
    id_usuario, 'Firulais', 'Perro', 'Labrador', DATE '2020-05-10', 'MACHO'
FROM usuario WHERE correo = 'ana.cliente@petcore.com';

INSERT INTO mascota
    (id_cliente, nombre, especie, raza, fecha_nacimiento, sexo)
SELECT
    id_usuario, 'Michi', 'Gato', 'Siamés', DATE '2021-08-20', 'HEMBRA'
FROM usuario WHERE correo = 'ana.cliente@petcore.com';


-- ============================================
-- TIPOS DE ATENCIÓN
-- ============================================

INSERT INTO tipo_atencion
    (nombre, descripcion, duracion_minutos, reservable_cliente)
VALUES
    ('Consulta general', 'Chequeo clínico de rutina', 30, TRUE),
    ('Vacunación', 'Aplicación de vacunas', 15, TRUE),
    ('Cirugía', 'Procedimiento quirúrgico', 60, FALSE);


-- ============================================
-- DISPONIBILIDAD DEL VETERINARIO
-- ============================================

-- Lunes a viernes de 09:00 a 13:00.
INSERT INTO disponibilidad (id_veterinario, dia_semana, hora_inicio, hora_fin)
SELECT id_usuario, dia, TIME '09:00', TIME '13:00'
FROM usuario, generate_series(1, 5) AS dia
WHERE correo = 'bruno.vet@petcore.com';


-- ============================================
-- TURNO DE EJEMPLO
-- ============================================

INSERT INTO turno
    (id_mascota, id_veterinario, id_tipo_atencion, id_usuario_creador,
     fecha_hora_inicio, fecha_hora_fin, duracion_minutos, canal_origen)
SELECT
    m.id_mascota,
    v.id_usuario,
    ta.id_tipo_atencion,
    c.id_usuario,
    (CURRENT_DATE + INTERVAL '7 days' + TIME '09:00')::timestamptz,
    (CURRENT_DATE + INTERVAL '7 days' + TIME '09:30')::timestamptz,
    30,
    'AUTOGESTION'
FROM mascota m
JOIN usuario c ON c.id_usuario = m.id_cliente AND c.correo = 'ana.cliente@petcore.com'
JOIN usuario v ON v.correo = 'bruno.vet@petcore.com'
JOIN tipo_atencion ta ON ta.nombre = 'Consulta general'
WHERE m.nombre = 'Firulais';

COMMIT;

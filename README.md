# Pet-Core - Demostración de tácticas de arquitectura

Este proyecto utiliza una API REST desarrollada con FastAPI para demostrar tácticas de disponibilidad y seguridad. La demostración de disponibilidad combina replicación de la API, balanceo mediante Nginx y reintentos cuando una réplica no responde.

## Índice

- [Requisitos](#requisitos)
- [Preparación local](#preparación-local)
- [Levantar la aplicación](#levantar-la-aplicación)
- [Estructura](#estructura)
- [Importar las peticiones en Postman](#importar-las-peticiones-en-postman)
- [Demostración de seguridad con Postman](#demostración-de-seguridad-con-postman)
- [Demostración automática de autenticación](#demostración-automática-de-autenticación)
- [Demostración automática de autorización](#demostración-automática-de-autorización)
- [Demostración de replicación con Postman](#demostración-de-replicación-con-postman)
- [Demostración de reintentos con Postman](#demostración-de-reintentos-con-postman)
- [Demostración automática de replicación](#demostración-automática-de-replicación)
- [Demostración automática de reintentos](#demostración-automática-de-reintentos)
- [Demostración de atomicidad ACID](#demostración-de-atomicidad-acid)
- [Detener la aplicación](#detener-la-aplicación)
- [Datos de prueba](#datos-de-prueba)

## Requisitos

Comprobar que Git y Docker Desktop estén instalados:

```powershell
git --version
docker --version
docker compose version
docker info
```

Docker Desktop debe estar abierto. No es necesario instalar PostgreSQL, FastAPI ni Nginx manualmente.

## Preparación local

Abrir PowerShell en la carpeta del proyecto:

```powershell
cd "C:\ruta\Proyecto_Clínica_Veterinaria"
```

Crear la contraseña local de PostgreSQL:

```powershell
New-Item -ItemType Directory -Force db
Set-Content -Path db/password.txt -Value "CAMBIAR_POR_UNA_CONTRASENA"
```

Crear una clave aleatoria para los tokens JWT utilizando PowerShell:

```powershell
$bytes = New-Object byte[] 32
$generador = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$generador.GetBytes($bytes)
$generador.Dispose()
$jwtSecret = ([BitConverter]::ToString($bytes)).Replace("-", "").ToLower()
Set-Content -Path db/jwt-secret.txt -Value $jwtSecret -NoNewline
```

`db/password.txt` y `db/jwt-secret.txt` contienen información sensible, no se guardan en Git y cada integrante debe crear los suyos.

## Levantar la aplicación

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\andis-up.ps1
```

El script construye las imágenes y levanta PostgreSQL, el frontend, Nginx y dos réplicas de FastAPI.

- Frontend: http://localhost:5173
- API: http://localhost:8000
- Documentación: http://localhost:8000/docs

Comprobar los contenedores:

```powershell
docker compose ps
```

Deben aparecer dos contenedores pertenecientes al servicio `server`.

## Estructura

```text
Postman
   |
   v
Nginx :8000
   |------> FastAPI replica 1 :8000
   |------> FastAPI replica 2 :8000
                       |
                       v
                  PostgreSQL
```

Nginx distribuye las solicitudes entre las réplicas. Si una conexión falla, intenta enviar la solicitud a la otra disponible.

El endpoint de demostración es:

```http
GET /demo/instancia
```

Ejemplo de respuesta:

```json
{
  "instancia": "dc0948ef34a5"
}
```

El valor es el hostname asignado por Docker al contenedor que respondió. Cada réplica tiene uno diferente.

## Importar las peticiones en Postman

1. Abrir Postman y seleccionar **Import**.
2. Seleccionar `UT3_TFU Escalado.postman_collection`.
3. Abrir la colección que se quiera utilizar.
4. Las colecciones utilizan direcciones explícitas con `http://localhost:8000`; no requieren configurar un Environment ni una variable `base_url`.
5. Después de cada petición de inicio de sesión, copiar manualmente el valor de `access_token` y pegarlo en **Authorization > Bearer Token** de las peticiones siguientes indicadas por la colección.

El endpoint de demostración requiere un token válido, pero acepta cualquier rol autenticado. Manejar el JWT manualmente permite ver con claridad qué dato devuelve el login y qué dato se envía después en el encabezado `Authorization`.

---
# Demostración de escalabilidad horizontal y servicio sin estado con Postman

### 1. Levantar las dos réplicas

Levantar la aplicación:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\andis-up.ps1
```

Comprobar los contenedores:

```powershell
docker compose ps
```

Deben aparecer dos contenedores pertenecientes al servicio `server`, además de Nginx y PostgreSQL.

La existencia de dos instancias del backend constituye la primera evidencia de **escalabilidad horizontal**, ya que la capacidad del sistema se amplió agregando una nueva réplica en lugar de aumentar CPU o memoria de una única instancia.

---

### 2. Comprobar el balanceo entre las réplicas

Ejecutar varias veces:

```http
GET http://localhost:8000/demo/instancia
```

Las respuestas deben alternar entre dos identificadores distintos porque existen dos contenedores ejecutando la misma API detrás de Nginx.

Por ejemplo:

```json
{
    "instancia": "35e8f980a65e"
}
```

En **Headers** también se pueden observar:

```text
X-Upstream-Addr
X-Upstream-Status
```

`X-Upstream-Addr` permite identificar qué réplica procesó la solicitud y `X-Upstream-Status` muestra el resultado devuelto por la API.

Aunque las solicitudes son atendidas por diferentes instancias, el cliente utiliza siempre la misma dirección:

```text
http://localhost:8000
```

Esto demuestra que Nginx actúa como balanceador y distribuye las solicitudes entre las réplicas disponibles.

---

### 3. Comprobar que el mismo JWT funciona en ambas réplicas

Ejecutar varias veces:

```http
GET http://localhost:8000/mascotas
```

utilizando el mismo Bearer Token obtenido durante el inicio de sesión.

En cada ejecución se debe comprobar:

```text
Status: 200 OK
```

y observar el encabezado:

```text
X-Upstream-Addr
```

Las peticiones deben ser procesadas por ambas réplicas y el mismo JWT debe funcionar independientemente de cuál de ellas atienda la solicitud.

Esto demuestra que la autenticación no depende de una sesión almacenada únicamente en la memoria de una réplica.

El JWT contiene la información necesaria para identificar al usuario y ambas instancias pueden validarlo porque utilizan la misma configuración de seguridad.

---

### 4. Modificar una mascota desde una réplica

Primero ejecutar:

```http
GET http://localhost:8000/mascotas
```

y seleccionar una mascota cuyo estado sea:

```text
ACTIVA
```

Copiar su `id_mascota`.

Luego ejecutar, reemplazando `1` por el identificador correspondiente:

```http
PATCH http://localhost:8000/mascotas/1/inactivar
```

Esta petición no necesita body, la respuesta esperada es:

```text
200 OK
```

Con un resultado similar a:

```json
{
  "id_mascota": 1,
  "estado": "INACTIVA"
}
```
Registrar también:

```text
X-Upstream-Addr
```

Ese encabezado permite identificar qué réplica realizó la modificación.

---

### 5. Restaurar la mascota

Para dejar los datos como estaban antes de la demostración, ejecutar:

```http
PATCH http://localhost:8000/mascotas/1/activar
```

utilizando el mismo Bearer Token, la respuesta esperada es:

```json
{
  "id_mascota": 1,
  "estado": "ACTIVA"
}
```

Luego volver a ejecutar:

```http
GET http://localhost:8000/mascotas
```

y comprobar que la mascota también aparece como `ACTIVA` cuando la petición es atendida por la otra réplica.

---

### 6. ¿Por qué se demuestra escalabilidad horizontal?

La evidencia conjunta es:

- Docker muestra dos réplicas del servicio `server`.
- `GET /demo/instancia` devuelve identificadores de contenedores diferentes.
- `X-Upstream-Addr` confirma que distintas solicitudes son atendidas por distintas instancias.
- Los clientes utilizan siempre una única dirección.
- Nginx distribuye las solicitudes entre las réplicas.

Esto demuestra **escalabilidad horizontal** porque el sistema aumenta su capacidad agregando nuevas instancias del backend.

---

### 7. ¿Por qué se demuestra que el servicio es sin estado?

La evidencia conjunta es:

- El usuario inicia sesión una sola vez.
- El mismo JWT funciona en ambas réplicas.
- Ninguna réplica necesita recordar localmente la sesión del usuario.
- Una réplica puede modificar una mascota.
- Otra réplica puede consultar inmediatamente el cambio.
- Los datos persistentes se encuentran en PostgreSQL.

Un servicio sin estado no depende de información guardada en la memoria de una instancia para poder atender la siguiente solicitud.

En PetCore, la identidad del usuario viaja en cada petición mediante el JWT:

```text
Authorization: Bearer TOKEN
```

y los datos de negocio se almacenan en PostgreSQL.

Por eso cualquier réplica puede atender cualquier solicitud.

---


### 8. Demostración de atomicidad ACID

Antes de probar la demo, es necesario cerrar una de las réplicas. Porque sino es probable que una de las réplicas siga funcionando y no demuestre una falla.
Se puede hacer directo desde docker deteniendo uno de los servers en ejecución

Esta demostración verifica la propiedad de **atomicidad** de las transacciones de PostgreSQL.

En Pet-Core, registrar una consulta clínica implica realizar varios cambios sobre la base de datos. Estos cambios forman parte de una misma operación transaccional, por lo que, si la operación falla, los cambios realizados deben revertirse y la base debe quedar en el mismo estado que tenía antes de comenzar.

La demostración se realiza siguiendo este flujo:

```text
Login como cliente
       ↓
Reservar un turno
       ↓
Login como veterinario
       ↓
Consultar estado del turno
       ↓
Armar falla
       ↓
Registrar consulta
       ↓
Falla intencional
       ↓
Consultar estado nuevamente
       ↓
El turno continúa CONFIRMADO
```
Iniciar sesión como cliente:
Ejecutar:

```http
POST /auth/login
```
con las credenciales del cliente:
```json
{
  "correo": "ana.cliente@petcore.com",
  "contrasena": "contraSegura123"
}
```
Luego con el token del cliente, ejecutar:
```http
POST /turnos
```
Guardar el id del turno recién creado, debería ser 2. El mismo debe quedar en estado "CONFIRMADO".

Luego iniciar sesión cómo veterinario:
```http
POST /auth/login
```
Una vez iniciado sesión con las credenciales de veterinario. Se puede proceder a forzar una falla para comprobar que el sistema cumple con ACID.

Primero consultar el estado inicial del turno:
```http
GET /debug/estado-turno/{{id_turno}}
```
La respuesta debería indicar:

```json
estado_turno = CONFIRMADO
```
Después, hay que ejecutar el endpoint que permite forzar la falla a la hora de intentar dejar la consulta como "ATENDIDO" 
Ejecutar:

```http
POST /debug/simular-falla-registrar-consulta
```
Luego, hay que intentar registrar la consulta, debido a la falla anterior, al ejecutar:

```http
POST /turnos/{{id_turno}}/consulta
```
La respuesta esperada es:

```json
500 Internal Server Error
```
Ya que debido a la falla, no se puedo actualizar el estado de la consulta correctamente

Pero para verificar que realmente cumple con ACID, hay que verificar que el estado genuinamente no ha cambiado. Para eso ejecutar otra vez:

```http
GET /debug/estado-turno/{{id_turno}}
```

Debería mantenerse en "CONFIRMADO"

Esto demuestra la atomicidad de la transacción: aunque la operación haya comenzado a modificar la base, al producirse la falla los cambios se revierten y no queda un estado intermedio.

---

## Datos de prueba

La primera vez que se crea el volumen de PostgreSQL, `db/init/` carga el esquema y los datos de prueba. La contraseña de estos usuarios es `contraSegura123`:

| Correo | Rol |
| --- | --- |
| `ana.cliente@petcore.com` | Cliente |
| `bruno.vet@petcore.com` | Veterinario |
| `carla.admin@petcore.com` | Administrador |

Para reconstruir la base desde cero:

```powershell
docker compose down --volumes
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\andis-up.ps1
```

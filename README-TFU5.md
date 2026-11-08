# Pet-Core — TFU5: arquitectura basada en eventos y servicio SOAP

En esta entrega separamos la generación de PDF de la API y pasamos la consulta del historial a SOAP. Este README explica cómo funciona y cómo probarlo.

## Índice

- [Qué se hizo](#qué-se-hizo)
- [Cómo levantar la aplicación](#cómo-levantar-la-aplicación)
- [Exportación del historial a PDF (eventos)](#exportación-del-historial-a-pdf-eventos)
- [Servicio SOAP del historial](#servicio-soap-del-historial)
- [Qué pasa cuando algo falla](#qué-pasa-cuando-algo-falla)
- [Cómo probarlo](#cómo-probarlo)
- [Variables de configuración](#variables-de-configuración)
- [Limitaciones](#limitaciones)
- [Archivos nuevos](#archivos-nuevos)

## Qué se hizo

Antes la API armaba el PDF. Si se caía en el medio, el trabajo quedaba sin terminar.

Ahora se reparte así:

```text
Veterinario
    |
    v
  API  --(1) ExportacionSolicitada-->  RabbitMQ  -->  Worker
   ^                                                    |
   |                                                    | (2) pide el historial
   |                                                    v
   |                                               Servicio SOAP  (contenedor aparte)
   |                                                    |
   |                                                    v
   |                                                 PostgreSQL
   |
   +<--(3) ExportacionGenerada / ExportacionFallida-- RabbitMQ <-- Worker (PDF listo)
```

| Pieza | Qué hace |
|---|---|
| **API** | Recibe el pedido, guarda la tarea, publica el evento, consulta el estado y entrega la descarga. |
| **RabbitMQ** | Guarda los eventos hasta que alguien los procese. |
| **Worker** | Recibe pedidos, busca el historial, arma el PDF y avisa cómo salió. |
| **Servicio SOAP** | Entrega el historial por XML y publica el contrato WSDL (`historial-soap`). |

La consulta `GET /mascotas/{id}/historial` (la que usa el frontend) también pasa por el servicio SOAP.

## Cómo levantar la aplicación

Primero creá `db/password.txt` y `db/jwt-secret.txt`, como dice *Preparación local* en el [README.md](README.md).

Con Docker Desktop abierto:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\andis-up.ps1
```

Levanta PostgreSQL, Redis, RabbitMQ, el servicio SOAP, dos réplicas de la API, el worker y Nginx.

| Qué | Dirección |
|---|---|
| API (por Nginx) | http://localhost:8000 |
| Documentación de la API | http://localhost:8000/docs |
| Servicio SOAP | http://localhost:8001/soap/historial |
| WSDL | http://localhost:8001/soap/historial?wsdl |
| Consola de RabbitMQ | http://localhost:15672 (usuario y clave: `petcore`) |

Para ver los contenedores: `docker compose ps`.

**Si ya tenías la base:** los archivos de `db/init/` se ejecutan solo al crearla. Agregá la columna del Outbox con este comando:

```powershell
Get-Content .\db\init\07_outbox_exportacion.sql -Raw | docker exec -i postgres-dev psql -U postgres -d postgres
```

## Exportación del historial a PDF (eventos)

### Cómo funciona

1. El veterinario pide `POST /historial/{id_mascota}/exportar`.
2. La API guarda la tarea como `PENDIENTE`, manda `ExportacionSolicitada` a RabbitMQ y devuelve **202** con el `id_tarea`.
3. El worker toma el pedido y busca el historial por SOAP.
4. Arma el PDF, lo guarda en la carpeta compartida y avisa con `ExportacionGenerada` o `ExportacionFallida`.
5. La API recibe ese resultado y pasa la tarea a `LISTO` (o `ERROR`).
6. El veterinario consulta `GET /historial/exportar/{id_tarea}`. Si está `LISTO`, recibe un enlace temporal para bajar el PDF sin iniciar sesión.

### Eventos

Todos llevan `id_tarea`, que identifica la exportación.

| Evento | Quién lo publica | Datos |
|---|---|---|
| `ExportacionSolicitada` | API | `id_tarea`, `id_mascota`, `id_veterinario` |
| `ExportacionGenerada` | Worker | `id_tarea`, `archivo` |
| `ExportacionFallida` | Worker | `id_tarea`, `motivo` |

### Endpoints

| Endpoint | Quién lo usa | Qué hace |
|---|---|---|
| `POST /historial/{id_mascota}/exportar` | Veterinario | Crea la tarea y responde 202. |
| `GET /historial/exportar/{id_tarea}` | Veterinario | Dice si está `PENDIENTE`, `LISTO` o `ERROR`. Si está `LISTO`, trae el enlace. |
| `GET /historial/exportar/{id_tarea}/descargar?token=...` | Cualquiera con el enlace | Entrega el PDF. |

## Servicio SOAP del historial

El historial se consulta en un servicio aparte, en la carpeta `SOAP` y el contenedor `historial-soap`. Usa mensajes XML y tiene su contrato WSDL.

El resto, incluido el login, sigue en la API REST.

La configuración, conexión a la base, middleware JWT, repositorio y DTO compartidos están en `app/`. El `SOAP/Dockerfile` los copia desde ahí. En `SOAP/` queda lo propio del servicio, sin duplicar esos archivos.

### Quién lo usa

- **El worker:** pide el historial del veterinario para armar el PDF.
- **La API REST:** `GET /mascotas/{id}/historial` pide los datos al SOAP en vez de consultar la base.

Los dos usan el mismo cliente: `app/historial/cliente_historial.py`.

### Seguridad y reglas de negocio

SOAP usa el mismo middleware JWT. Para probarlo, iniciá sesión en la API y mandá el access token en `Authorization: Bearer TOKEN`.

Valida firma, vencimiento, issuer, audience y los claims requeridos con la misma clave JWT, guardada como secreto de Docker.

- **API REST:** reenvía el token del propio usuario.
- **Worker:** crea un token de 2 minutos a nombre del veterinario con esa misma clave.

El veterinario ve todo el historial. El cliente ve el de sus mascotas, paginado. El administrador no puede verlo. Los accesos quedan en la auditoría.

### Errores

SOAP devuelve un SOAP Fault con el código original (400, 401, 403, 404, 503). La API lo pasa a HTTP. Por ejemplo, si la mascota no existe, devuelve 404.

### Prueba con Postman

1. En Postman: **Import** y elegir `postman/Eventos_SOAP_Collection.json`.
2. Con la aplicación levantada, ejecutar los pasos **en orden** con **Send**, o todos juntos con **Run collection**.

Cada paso usa lo que guardó el anterior (los tokens, el id de la mascota, el id de la tarea), así que **hay que respetar el orden**. No hace falta copiar nada a mano: los scripts de la colección lo guardan solos.

Para saber si un paso salió bien, mirá la pestaña **Test Results** de la respuesta: tiene que verse en verde. En algunos pasos el error es justamente lo esperado (se avisa en cada uno).

**Usuarios de prueba** (la contraseña de todos es `contraSegura123`):

| Correo | Rol | Qué ve en el historial |
|---|---|---|
| `ana.cliente@petcore.com` | Cliente | El historial de sus mascotas, con paginación. |
| `bruno.vet@petcore.com` | Veterinario | El historial completo, con correcciones. |
| `carla.admin@petcore.com` | Administrador | Nada: recibe un error 403. |

#### Paso a paso

**1.1, 1.2 y 1.3 — Iniciar sesión.** Apretá **Send** en los tres (cliente, veterinario y administrador): cada uno guarda el token de un rol y los pasos siguientes los usan. Ves `200` y un `access_token`. Los tokens duran 15 minutos: si después da 401, repetí los tres.

**2.1 — Ver las mascotas.** Lista las mascotas de Ana y guarda el id de Firulais. Ves `200` y una lista con Firulais y Michi.

**2.2 — Registrar una consulta (opcional, una sola vez).** El veterinario carga una consulta en el turno 1 para que el historial tenga contenido. Ves `200`; si ya estaba registrada, un error, y es normal.

**3.1 — Ver el WSDL.** Pide el contrato del servicio SOAP. Ves `200` y un XML que menciona `ObtenerHistorialMascota`.

**3.2 — Historial como cliente (SOAP).** Llama al servicio SOAP con el token del cliente. Ves `200` y un XML con `<h:cliente>`.

**3.3 — Historial como veterinario (SOAP).** Igual, con el token del veterinario. Ves `200` y un XML con `<h:veterinario>`, más completo.

**3.4 — Administrador (SOAP).** Igual, con el token del administrador, que no tiene acceso. Ves HTTP `500` con un `soap:Fault` y `<status>403</status>`. **El error es lo correcto:** SOAP devuelve los errores así, con el código real dentro del XML.

**3.5 — Mascota inexistente (SOAP).** Pide la mascota 99999. Ves HTTP `500` con un `soap:Fault` y `<status>404</status>`. **El error es lo correcto.**

**4.1 — Historial como veterinario (REST).** Pide el historial a la API, que por dentro se lo pide al servicio SOAP. Ves `200` y el historial en JSON.

**4.2 — Historial como cliente, paginado (REST).** Igual, con `?limite=2`. Ves `200` y como máximo 2 consultas.

**4.3 — Administrador (REST).** Ves `403`. **El error es lo correcto.**

**4.4 — Mascota inexistente (REST).** Ves `404`. **El error es lo correcto.**

**5.1 — Pedir la exportación.** La API guarda la tarea, avisa al worker por RabbitMQ y responde sin esperar al PDF. Ves `202` y `"estado": "PENDIENTE"`.

**5.2 — Consultar el estado.** En **Run collection** se repite sola; con **Send**, apretalo hasta ver `LISTO`. El worker arma el PDF en unos segundos (hace una pausa a propósito). Ves `PENDIENTE` y después `LISTO` con un `enlace_descarga`.

**5.3 — Descargar el PDF.** Usa el enlace anterior, sin token. Ves `200` y un PDF (pestaña **Preview**).

**WSDL:** `GET http://localhost:8001/soap/historial?wsdl` devuelve el contrato: operación, tipos de respuesta y dirección del servicio. No requiere token.

**Salud:** `GET http://localhost:8001/health` comprueba el acceso a PostgreSQL y responde `{"status": "ok"}`.

## Qué pasa cuando algo falla

| Situación | Qué hace el sistema | Patrón |
|---|---|---|
| El worker se detiene | Las solicitudes esperan en la cola y se procesan cuando vuelve. | Cola de mensajes durable |
| RabbitMQ no responde al pedir la exportación | La API acepta (202) y guarda el evento pendiente. El reenviador lo manda cuando RabbitMQ vuelve. | Outbox |
| La API se cae después de guardar la tarea y antes de publicar | Lo mismo: el evento pendiente se reenvía solo. | Outbox |
| La API se reinicia con tareas pendientes | Las tareas siguen en la base y los resultados esperan en su cola. | Cola durable + estado en la base |
| El servicio SOAP está caído | El worker hace hasta 3 intentos, esperando más entre cada uno. Si sigue fallando, marca `ERROR`. | Retry |
| La misma solicitud llega dos veces | Si el PDF ya existe, el worker solo avisa que está listo. | Idempotencia |
| Llega un mensaje inválido | Se aparta a una cola de mensajes muertos y el worker sigue. | Dead letter |
| Hay muchas solicitudes juntas | El worker procesa de a una; las demás esperan en la cola. | Queue-Based Load Leveling |
| El pedido tarda en procesarse | La API responde 202 sin esperar el PDF. El veterinario consulta el estado después. | Asynchronous Request-Reply |

## Cómo probarlo

### Demo corta

Dura alrededor de un minuto y medio.

1. Levantá la aplicación, si no está arriba: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\andis-up.ps1`.
2. Abrí PowerShell en la carpeta del proyecto y corré:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo-exportacion-eventos.ps1 -Demo
```

**Qué hace, en orden:**
- **Exportación normal:** pide una exportación, espera a que termine y descarga el PDF sin iniciar sesión.
- **Worker caído:** detiene el worker, pide 3 exportaciones (quedan `PENDIENTE`), lo vuelve a levantar y se completan las 3.
- **RabbitMQ caído:** lo detiene y pide una exportación (la API igual la acepta). Al volver RabbitMQ, la tarea se completa.
- **SOAP caído:** lo detiene y la tarea termina en `ERROR` después de los reintentos. Al volver el SOAP, una exportación nueva funciona.

**Qué tenés que ver:** cada verificación muestra `[OK]` o `[FALLO]`. Al final tiene que decir `Verificaciones: 10. Fallos: 0.` Los números de los casos saltan (1, 3, 6, 8) porque el modo completo tiene otros.

**Importante:**
- El script apaga y vuelve a levantar el worker, RabbitMQ y el servicio SOAP a propósito. Al terminar deja todo funcionando.
- Si alguna verificación da `[FALLO]`, revisá con `docker compose ps` que todos los servicios estén levantados y volvé a correrlo.

### Pruebas completas

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo-exportacion-eventos.ps1
```

Corre los 9 casos (21 verificaciones). Agrega la consulta REST por SOAP con todos los roles, reinicio de la API, Outbox y mensajes duplicados e inválidos.

### Comparación con la versión anterior

`scripts\medir-interrupcion.ps1` compara la versión anterior con la nueva. Pide 5 exportaciones, corta 10 segundos el proceso que arma los PDF (en la anterior, la API; en la nueva, el worker) y muestra cuántas se aceptaron, terminaron, quedaron pendientes o dieron error, y cuánto tardó.

Se corre **una versión por vez**, desde la carpeta de esa versión. Para la nueva, con la aplicación levantada:

```powershell
# Corte de golpe (simula una caída)
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\medir-interrupcion.ps1 -Arquitectura nueva

# Apagado normal
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\medir-interrupcion.ps1 -Arquitectura nueva -Ordenada
```

Para la versión anterior hay que levantarla aparte. Los pasos están en [RESULTADOS_PRUEBAS_EVENTOS.md](RESULTADOS_PRUEBAS_EVENTOS.md#cómo-repetir-la-comparación), junto con los resultados.

En esa prueba, al cortar el proceso de golpe, la versión anterior dejó las 5 tareas pendientes. La nueva completó las 5 al volver el worker. Tardó más porque procesa de a un pedido.

### Ver las colas

En la consola de RabbitMQ (http://localhost:15672) se ven las colas `exportaciones.solicitadas`, `exportaciones.resultados` y `exportaciones.solicitadas.muertas`.

## Variables de configuración

Se configuran en `app/config.py` y `compose.yaml`. Estos son los valores usados al levantar con Compose:

| Variable | Valor por defecto | Para qué sirve |
|---|---|---|
| `RABBITMQ_HOST` / `RABBITMQ_PORT` | `rabbitmq` / `5672` | Dónde está RabbitMQ. |
| `RABBITMQ_USER` / `RABBITMQ_PASSWORD` | `petcore` / `petcore` | Credenciales de RabbitMQ. |
| `RABBITMQ_INTENTOS` | `3` | Intentos al publicar un evento. |
| `OUTBOX_INTERVALO_SEGUNDOS` | `5` | Cada cuánto la API revisa los eventos sin publicar. |
| `OUTBOX_ANTIGUEDAD_SEGUNDOS` | `10` | Antigüedad mínima de una tarea para reenviar su evento. |
| `WORKER_INTENTOS_HISTORIAL` | `3` | Intentos del worker al pedir el historial. |
| `WORKER_ESPERA_BASE_SEGUNDOS` | `1` | Espera entre intentos (se duplica cada vez). |
| `SOAP_HISTORIAL_URL` | `http://historial-soap:8001/soap/historial` | Dirección del servicio SOAP. |
| `SOAP_TIMEOUT_SEGUNDOS` | `4` | Cuánto se espera la respuesta del servicio SOAP. |
| `EXPORTACION_RETARDO_SEGUNDOS` | `5` | Pausa de la demo para ver `PENDIENTE`. Para uso real, poner `0`. |

## Limitaciones

- API, worker y SOAP dependen de la misma base PostgreSQL. Los PDF se guardan en un volumen compartido entre API y worker.
- Hay un solo worker y atiende de a un pedido. Se pueden levantar más usando la misma cola.
- Para detectar duplicados se busca `{id_tarea}.pdf`. Si existe, se toma como terminado.
- Si la API y RabbitMQ están caídos, las tareas quedan en `PENDIENTE` hasta que vuelvan. No hay tiempo maximo de espera.
- El worker tiene la clave JWT compartida y puede crear tokens a nombre de cualquier veterinario.
- Las credenciales de RabbitMQ por defecto (`petcore`/`petcore`) son solo para la demo.

## Archivos nuevos

Estos son los archivos que agregamos y para qué sirve cada uno.

| Archivo | Qué contiene |
|---|---|
| `app/mensajeria/eventos.py` | Nombres de colas y formato de los eventos. |
| `app/mensajeria/rabbitmq.py` | Conexión con RabbitMQ, creación de colas y publicación. |
| `app/worker/main.py` | El worker de exportaciones. |
| `app/historial/cliente_historial.py` | Cliente del servicio SOAP (lo usan el worker y la API). |
| `app/historial/consumidor_resultados.py` | La API recibe los resultados del worker. |
| `app/historial/reenviador_eventos.py` | Reenvío de eventos sin publicar (Outbox). |
| `db/init/07_outbox_exportacion.sql` | Columna `evento_publicado` de la tabla de tareas. |
| `SOAP/` | Servicio SOAP: `main.py`, `distribuido/` (XML y WSDL) y `historial/service.py`. |
| `scripts/demo-exportacion-eventos.ps1` | Demo y pruebas de los escenarios. |
| `scripts/medir-interrupcion.ps1` | Medición para comparar con la versión anterior. |
| `postman/Eventos_SOAP_Collection.json` | Colección de Postman para probar el SOAP, la API REST y la exportación a PDF. |
| `RESULTADOS_PRUEBAS_EVENTOS.md` | Resultados de las pruebas y de la comparación. |

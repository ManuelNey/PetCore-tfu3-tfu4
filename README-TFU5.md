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

### Prueba manual con Postman

1. **POST** `http://localhost:8000/auth/login` → copiar el `access_token`.
2. **GET** `http://localhost:8000/mascotas` con el token → copiar el `id_mascota` de una mascota que tenga consultas.
3. **POST** `http://localhost:8001/soap/historial` con el mismo token en **Authorization → Bearer Token**.

Encabezados:

| Encabezado | Valor |
|---|---|
| `Content-Type` | `text/xml; charset=utf-8` |
| `SOAPAction` | `"urn:petcore:historial/ObtenerHistorialMascota"` |

En **Body → raw → XML**, pegá esto y cambiá `1` por el ID de la mascota:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope
    xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:h="urn:petcore:historial">
  <soap:Body>
    <h:ObtenerHistorialMascota>
      <h:id_mascota>1</h:id_mascota>
      <h:limite>10</h:limite>
      <h:offset>0</h:offset>
    </h:ObtenerHistorialMascota>
  </soap:Body>
</soap:Envelope>
```

**WSDL:** `GET http://localhost:8001/soap/historial?wsdl` devuelve el contrato: operación, tipos de respuesta y dirección del servicio. No pide token.

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

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo-exportacion-eventos.ps1 -Demo
```

Prueba 4 casos: exportación normal y caídas del worker, RabbitMQ y SOAP. Cada verificación muestra `[OK]` o `[FALLO]`.

### Pruebas completas

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo-exportacion-eventos.ps1
```

Corre los 9 casos (21 verificaciones). Agrega la consulta REST por SOAP con todos los roles, reinicio de la API, Outbox y mensajes duplicados e inválidos.

### Comparación con la versión anterior

`scripts\medir-interrupcion.ps1` pide 5 exportaciones y frena el proceso que arma los PDF. Los resultados y los pasos para repetirlo están en [RESULTADOS_PRUEBAS_EVENTOS.md](RESULTADOS_PRUEBAS_EVENTOS.md).

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
| `RESULTADOS_PRUEBAS_EVENTOS.md` | Resultados de las pruebas y de la comparación. |

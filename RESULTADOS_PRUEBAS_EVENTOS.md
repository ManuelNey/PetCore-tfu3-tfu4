# Pruebas de exportación del historial con eventos

## Cómo correr las pruebas

| Qué | Cómo |
|---|---|
| Escenarios completos (21 verificaciones) | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo-exportacion-eventos.ps1` |
| Demo corta (4 escenarios, alrededor de 1 minuto y medio) | el mismo script con `-Demo` |
| Comparación anterior / nueva | `scripts\medir-interrupcion.ps1` (ver más abajo) |

Primero levantá la aplicación con `scripts\andis-up.ps1`.

## Qué probamos

En la prueba registrada pasaron las 21 verificaciones.

| Escenario | Qué pasó |
|---|---|
| 1. Exportación normal | La API respondió 202, la tarea llegó a `LISTO` y pudimos bajar el PDF sin login. |
| 2. Consulta REST vía SOAP | El veterinario recibió 200 y el cliente su historial paginado. El administrador recibió 403 y una mascota inexistente, 404. El WSDL estuvo disponible. |
| 3. Worker detenido y reiniciado | Al frenar el worker, los 3 pedidos quedaron `PENDIENTE`. Cuando volvió, completó los 3. |
| 4. API reiniciada | La tarea siguió guardada después de reiniciar la API y se completó al volver el worker. |
| 5. Outbox | Guardamos una tarea sin publicar su evento. El reenviador lo mandó después. |
| 6. RabbitMQ caído | La API aceptó el pedido (202). El evento quedó pendiente y se envió al volver RabbitMQ. |
| 7. Mensaje duplicado | Mandamos el mismo pedido dos veces. El PDF no se generó de nuevo: el archivo quedó igual. |
| 8. Servicio SOAP caído | Después de 3 intentos la tarea quedó en `ERROR`. Al volver SOAP, los nuevos pedidos funcionaron. |
| 9. Mensaje inválido | El mensaje fue a la cola de mensajes muertos y el worker siguió atendiendo pedidos. |

## Comparación con la versión anterior

Pedimos 5 exportaciones y, después de que la API las aceptó, frenamos por 10 segundos el proceso que arma los PDF:

- **Versión anterior** (commit `393742c`, `BackgroundTasks`): frenamos las réplicas de la API, que armaban los PDF.
- **Versión nueva**: frenamos el worker.

Usamos Docker Desktop en Windows, la misma máquina y los mismos datos. Había 2 réplicas de la API y una pausa de 5 segundos por PDF para la demo (`EXPORTACION_RETARDO_SEGUNDOS`). Esperamos como maximo 90 segundos.

| Tipo de interrupción | Arquitectura | Aceptadas | Completadas | Pendientes al final | Tiempo hasta terminar |
|---|---|---|---|---|---|
| Caída abrupta (`docker kill`) | Anterior | 5 | **0** | **5** | no terminaron en 90 s |
| Caída abrupta (`docker kill`) | Nueva | 5 | **5** | 0 | 39.7 s |
| Apagado ordenado (`docker stop`) | Anterior | 5 | 5 | 0 | 9.4 s |
| Apagado ordenado (`docker stop`) | Nueva | 5 | 5 | 0 | 39.6 s |

## Cómo repetir la comparación

Se mide una versión por vez, así que hay que cambiar de una a otra. El contenedor de la base de datos y los puertos (8000, 5432) son los mismos en las dos, por eso no pueden estar levantadas a la vez.

**1. Medir la versión nueva.** Con la aplicación levantada (`andis-up.ps1`), desde la carpeta del proyecto:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\medir-interrupcion.ps1 -Arquitectura nueva
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\medir-interrupcion.ps1 -Arquitectura nueva -Ordenada
```

La primera corre el corte de golpe y la segunda el apagado normal. Anotá los resultados.

**2. Preparar la versión anterior** (el commit `393742c`, la del final de la TFU4). Esto solo lee el commit: no cambia tu repositorio.

```powershell
$anterior = "$env:TEMP\petcore-anterior"
git archive --format=zip -o "$env:TEMP\anterior.zip" 393742c
Expand-Archive "$env:TEMP\anterior.zip" -DestinationPath $anterior
Copy-Item db\password.txt, db\jwt-secret.txt "$anterior\db\"
```

**3. Bajar la versión nueva.** No borra tus datos:

```powershell
docker compose down
```

**4. Levantar la versión anterior:**

```powershell
cd $anterior
docker compose up --build -d --scale server=2 db redis server
docker compose up --build -d --no-deps --force-recreate balanceador
docker compose ps
```

Esperá unos 30 segundos hasta que los servicios figuren como sanos.

**5. Medir la versión anterior.** Volvé a la carpeta del proyecto nuevo y corré el mismo script, indicando dónde está la anterior:

```powershell
cd C:\ruta\al\proyecto
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\medir-interrupcion.ps1 -Arquitectura anterior -Directorio $anterior
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\medir-interrupcion.ps1 -Arquitectura anterior -Directorio $anterior -Ordenada
```

**6. Volver a la versión nueva.** Esto borra los datos de la versión anterior, que son solo de prueba:

```powershell
cd $anterior
docker compose down -v
cd C:\ruta\al\proyecto
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\andis-up.ps1
```

Con las cuatro corridas (anterior y nueva, cada una con corte de golpe y con apagado normal) se arma la tabla de arriba.

## Qué vimos

- **Al cortar el proceso de golpe**, la versión anterior dejó las 5 tareas en `PENDIENTE`: el trabajo estaba en la memoria de la API y no se retomaba al reiniciar. En la nueva, RabbitMQ conservó los pedidos y el worker terminó los 5 al volver.
- **Al apagar normalmente**, las dos terminaron las 5 tareas. La API esperó a que terminaran los trabajos antes de cerrarse.
- **La nueva tardó más**: en el apagado normal fueron 39.6 s frente a 9.4 s. El worker atiende de a un pedido, con la pausa de 5 segundos de la demo. Antes los PDF se armaban en paralelo en las dos réplicas. En esta prueba mejoró la recuperación ante caídas, pero completar todos los pedidos llevó más tiempo.

## Cosas a tener en cuenta

- La pausa de 5 segundos es solo para ver `PENDIENTE` en la demo. Con valor 0 se elimina esa espera.
- Usamos un solo worker. Se pueden levantar más para repartir los pedidos de la misma cola.
- El Outbox permite reenviar el evento si la API cae después de guardar la tarea y antes de publicarlo. API, worker y SOAP siguen dependiendo de la misma base de datos.
- Medimos una vez por caso y en una sola máquina. Esto muestra qué pasó en esas pruebas; harían falta más mediciones para comparar el rendimiento.

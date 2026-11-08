# Pruebas de exportacion del historial a PDF.
#
# Primero levantar la app con scripts\andis-up.ps1
# Correr: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo-exportacion-eventos.ps1
#
# Sin parametros prueba los 9 casos. Con -Demo corre los 4 de la demo corta.
# Cada verificacion muestra [OK] o [FALLO].

param([switch]$Demo)

$Api = "http://localhost:8000"
$Resultados = @()
$Completo = -not $Demo

# ---------- Funciones ----------

# Muestra OK o FALLO y lo guarda para el resumen.
function Registrar($nombre, $ok, $detalle) {
    $marca = if ($ok) { "[OK]   " } else { "[FALLO]" }
    Write-Host "$marca $nombre - $detalle"
    $script:Resultados += [pscustomobject]@{ Nombre = $nombre; Ok = $ok }
}

function Titulo($texto) {
    Write-Host ""
    Write-Host "=== $texto ===" -ForegroundColor Cyan
}

# Llama a la API y devuelve la respuesta, con su codigo y tipo de contenido.
function Llamar($metodo, $ruta, $token) {
    $cabeceras = @{}
    if ($token) { $cabeceras["Authorization"] = "Bearer $token" }
    try {
        $r = Invoke-WebRequest -Uri "$Api$ruta" -Method $metodo -Headers $cabeceras -UseBasicParsing -TimeoutSec 30
        $cuerpo = $r.Content
        # Volvemos a leer el JSON como UTF-8 porque PowerShell 5.1 mezcla las tildes.
        if ($r.Headers["Content-Type"] -like "*json*") {
            $cuerpo = [Text.Encoding]::UTF8.GetString([Text.Encoding]::GetEncoding(28591).GetBytes($cuerpo))
        }
        return [pscustomobject]@{ Estado = [int]$r.StatusCode; Cuerpo = $cuerpo; Tipo = $r.Headers["Content-Type"] }
    } catch {
        $codigo = 0
        if ($_.Exception.Response) { $codigo = [int]$_.Exception.Response.StatusCode }
        return [pscustomobject]@{ Estado = $codigo; Cuerpo = $_.ErrorDetails.Message; Tipo = "" }
    }
}

# Hace login y guarda el token para los pedidos.
function Iniciar-Sesion($correo) {
    $cuerpo = @{ correo = $correo; contrasena = "contraSegura123" } | ConvertTo-Json
    $r = Invoke-RestMethod -Uri "$Api/auth/login" -Method Post -ContentType "application/json" -Body $cuerpo
    return $r.access_token
}

# Consulta la base y toma la primera linea del resultado.
function Sql($consulta) {
    $salida = docker compose exec -T db psql -U postgres -d postgres -tA -c $consulta 2>$null
    return "$($salida | Select-Object -First 1)".Trim()
}

# Pide el PDF y devuelve el codigo HTTP y el id de tarea.
function Pedir-Exportacion($token) {
    $r = Llamar "POST" "/historial/1/exportar" $token
    $id = $null
    if ($r.Estado -eq 202) { $id = ($r.Cuerpo | ConvertFrom-Json).id_tarea }
    return [pscustomobject]@{ Estado = $r.Estado; Id = $id }
}

# Consulta si la tarea sigue PENDIENTE, esta LISTO o dio ERROR.
function Estado-Tarea($token, $id) {
    $r = Llamar "GET" "/historial/exportar/$id" $token
    if ($r.Estado -ne 200) { return "?" }
    return ($r.Cuerpo | ConvertFrom-Json).estado
}

# Espera el estado que buscamos, con un limite para no quedar esperando siempre.
function Esperar-Estado($token, $id, $esperado, $segundos) {
    $limite = (Get-Date).AddSeconds($segundos)
    do {
        if ((Estado-Tarea $token $id) -eq $esperado) { break }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $limite)
    return (Estado-Tarea $token $id)
}

# Da tiempo a que arranque la API.
function Esperar-Api {
    $limite = (Get-Date).AddSeconds(60)
    do {
        if ((Llamar "GET" "/health" $null).Estado -eq 200) { break }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $limite)
}

# Da tiempo a que arranque SOAP.
function Esperar-Soap {
    $limite = (Get-Date).AddSeconds(60)
    do {
        try { if ((Invoke-WebRequest -Uri "http://localhost:8001/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { break } } catch { }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $limite)
}

# Reiniciamos la API y recreamos Nginx para que encuentre las replicas nuevas.
function Reiniciar-Api {
    docker compose restart server | Out-Null
    docker compose up -d --no-deps --force-recreate balanceador 2>&1 | Out-Null
    Esperar-Api
}

# Corre este Python dentro del worker.
function Python-En-Worker($codigo) {
    $codigo | docker compose exec -T worker uv run python - 2>&1 | Out-Null
}

# Cuenta cuantos mensajes quedaron en la cola de muertos.
function Mensajes-Muertos {
    $lineas = docker compose exec -T rabbitmq rabbitmqctl list_queues name messages 2>$null
    $linea = $lineas | Where-Object { $_ -like "exportaciones.solicitadas.muertas*" }
    return [int]($linea -replace '.*\s', '')
}

# ---------- Preparacion ----------

Titulo "Preparacion"
docker compose up -d rabbitmq historial-soap worker 2>&1 | Out-Null
Esperar-Api
$vet = Iniciar-Sesion "bruno.vet@petcore.com"
$cli = Iniciar-Sesion "ana.cliente@petcore.com"
$adm = Iniciar-Sesion "carla.admin@petcore.com"
Write-Host "Sesiones iniciadas (veterinario, cliente, administrador)."

# ---------- 1. Exportacion normal ----------

Titulo "1. Exportacion normal: API -> RabbitMQ -> worker -> SOAP -> PDF"
$t = Pedir-Exportacion $vet
Registrar "1a. La API acepta la solicitud" ($t.Estado -eq 202) "HTTP $($t.Estado), tarea $($t.Id)"

$e = Esperar-Estado $vet $t.Id "LISTO" 60
Registrar "1b. La tarea llega a LISTO" ($e -eq "LISTO") "estado final: $e"

$tarea = (Llamar "GET" "/historial/exportar/$($t.Id)" $vet).Cuerpo | ConvertFrom-Json
$d = Llamar "GET" $tarea.enlace_descarga $null
Registrar "1c. El PDF se descarga sin login" ($d.Estado -eq 200 -and $d.Tipo -like "*pdf*") "HTTP $($d.Estado), $($d.Tipo)"

# ---------- 2. Historial por la API (usa el SOAP por dentro) ----------

if ($Completo) {
    Titulo "2. Historial por la API REST, que usa el servicio SOAP por dentro"

    $r = Llamar "GET" "/mascotas/1/historial" $vet
    Registrar "2a. Veterinario ve el historial" ($r.Estado -eq 200 -and $r.Cuerpo -like '*"consultas"*') "HTTP $($r.Estado)"

    # Pedimos hasta 2 consultas. Si hay menos, debe traer las que haya.
    $r = Llamar "GET" "/mascotas/1/historial?limite=2" $cli
    $n = 0; $total = 0
    if ($r.Estado -eq 200) {
        $datos = $r.Cuerpo | ConvertFrom-Json
        $n = @($datos.consultas).Count
        $total = $datos.total
    }
    Registrar "2b. Cliente ve su historial paginado (limite=2)" ($r.Estado -eq 200 -and $n -eq [Math]::Min(2, $total)) "HTTP $($r.Estado), $n consultas de $total"

    $r = Llamar "GET" "/mascotas/1/historial" $adm
    Registrar "2c. Administrador no tiene acceso" ($r.Estado -eq 403) "HTTP $($r.Estado)"

    $r = Llamar "GET" "/mascotas/99999/historial" $vet
    Registrar "2d. Mascota inexistente da 404" ($r.Estado -eq 404) "HTTP $($r.Estado)"

    $w = Invoke-WebRequest -Uri "http://localhost:8001/soap/historial?wsdl" -UseBasicParsing
    Registrar "2e. El servicio SOAP publica su WSDL" ($w.StatusCode -eq 200 -and $w.Content -like "*ObtenerHistorialMascota*") "HTTP $($w.StatusCode)"
}

# ---------- 3. Worker detenido y reiniciado ----------

Titulo "3. Worker detenido y reiniciado: las solicitudes se conservan"
docker compose stop worker | Out-Null
$ids = @(1..3 | ForEach-Object { (Pedir-Exportacion $vet).Id })
Start-Sleep -Seconds 3
$pendientes = @($ids | Where-Object { (Estado-Tarea $vet $_) -eq "PENDIENTE" }).Count
Registrar "3a. Con el worker caido, las 3 solicitudes quedan esperando" ($pendientes -eq 3) "$pendientes de 3 en PENDIENTE"

docker compose start worker | Out-Null
$listas = @($ids | Where-Object { (Esperar-Estado $vet $_ "LISTO" 60) -eq "LISTO" }).Count
Registrar "3b. Al reiniciar el worker, se completan las 3" ($listas -eq 3) "$listas de 3 en LISTO"

# ---------- 4 y 5. API reiniciada y Outbox ----------

if ($Completo) {
    Titulo "4. API reiniciada despues de aceptar la tarea"
    docker compose stop worker | Out-Null
    $t = Pedir-Exportacion $vet
    Reiniciar-Api
    $e = Estado-Tarea $vet $t.Id
    Registrar "4a. Tras reiniciar la API, la tarea sigue registrada" ($e -eq "PENDIENTE") "estado: $e"

    docker compose start worker | Out-Null
    $e = Esperar-Estado $vet $t.Id "LISTO" 60
    Registrar "4b. Al volver el worker, la tarea se completa" ($e -eq "LISTO") "estado final: $e"

    Titulo "5. Outbox: tarea guardada con el evento sin publicar"
    # Guardamos la tarea directo en la base, como si la API hubiera caido antes de publicar.
    $id = Sql "INSERT INTO tarea_exportacion (id_mascota, id_usuario, evento_publicado) VALUES (1, 2, FALSE) RETURNING id_tarea"
    $publicado = Sql "SELECT evento_publicado FROM tarea_exportacion WHERE id_tarea = '$id'"
    Registrar "5a. La tarea queda con el evento sin publicar" ($publicado -eq "f") "evento_publicado = $publicado"

    $e = Esperar-Estado $vet $id "LISTO" 90
    $publicado = Sql "SELECT evento_publicado FROM tarea_exportacion WHERE id_tarea = '$id'"
    Registrar "5b. El reenviador publica el evento y la tarea se completa" ($e -eq "LISTO" -and $publicado -eq "t") "estado: $e, evento_publicado = $publicado"
}

# ---------- 6. RabbitMQ caido ----------

Titulo "6. RabbitMQ caido: la solicitud se acepta y se envia cuando vuelve"
docker compose stop rabbitmq | Out-Null
$t = Pedir-Exportacion $vet
Registrar "6a. Con RabbitMQ caido, la API igual acepta la solicitud" ($t.Estado -eq 202) "HTTP $($t.Estado)"

$publicado = Sql "SELECT evento_publicado FROM tarea_exportacion WHERE id_tarea = '$($t.Id)'"
Registrar "6b. El evento queda pendiente de publicar" ($publicado -eq "f") "evento_publicado = $publicado"

docker compose start rabbitmq | Out-Null
$e = Esperar-Estado $vet $t.Id "LISTO" 120
Registrar "6c. Al volver RabbitMQ, la tarea se completa" ($e -eq "LISTO") "estado final: $e"

# ---------- 7. Mensaje duplicado ----------

if ($Completo) {
    Titulo "7. Mensaje duplicado: la misma solicitud llega dos veces"
    $t = Pedir-Exportacion $vet
    Esperar-Estado $vet $t.Id "LISTO" 60 | Out-Null

    # Miramos la fecha del PDF para ver si lo vuelve a generar al repetir el pedido.
    $archivo = "/app/exportaciones/$($t.Id).pdf"
    $antes = docker compose exec -T worker stat -c "%Y" $archivo 2>$null | Select-Object -First 1
    Python-En-Worker @"
from app.mensajeria import eventos, rabbitmq
for _ in range(2):
    rabbitmq.publicar(eventos.RK_SOLICITADA, eventos.exportacion_solicitada('$($t.Id)', 1, 2))
"@
    Start-Sleep -Seconds 8
    $despues = docker compose exec -T worker stat -c "%Y" $archivo 2>$null | Select-Object -First 1

    $e = Estado-Tarea $vet $t.Id
    Registrar "7. Dos solicitudes repetidas no regeneran el PDF" ($e -eq "LISTO" -and $antes -eq $despues) "estado: $e, PDF sin cambios: $($antes -eq $despues)"
}

# ---------- 8. SOAP caido ----------

Titulo "8. Servicio SOAP caido: reintentos limitados y error claro"
docker compose stop historial-soap | Out-Null
$t = Pedir-Exportacion $vet
$e = Esperar-Estado $vet $t.Id "ERROR" 90
$motivo = ((Llamar "GET" "/historial/exportar/$($t.Id)" $vet).Cuerpo | ConvertFrom-Json).error
Registrar "8a. Tras los reintentos, la tarea queda en ERROR (no pendiente)" ($e -eq "ERROR") "estado: $e, motivo: $motivo"

docker compose start historial-soap | Out-Null
Esperar-Soap
$t = Pedir-Exportacion $vet
$e = Esperar-Estado $vet $t.Id "LISTO" 60
Registrar "8b. Con el SOAP de vuelta, las exportaciones funcionan" ($e -eq "LISTO") "estado final: $e"

# ---------- 9. Mensaje invalido ----------

if ($Completo) {
    Titulo "9. Mensaje invalido: va a la cola de mensajes muertos"
    $antes = Mensajes-Muertos
    Python-En-Worker @"
from app.mensajeria import eventos, rabbitmq
con, can = rabbitmq.abrir_canal()
can.basic_publish(eventos.EXCHANGE, eventos.RK_SOLICITADA, b'esto no es json')
con.close()
"@
    Start-Sleep -Seconds 5
    $despues = Mensajes-Muertos
    Registrar "9. El mensaje invalido se aparta y el worker sigue" ($despues -eq ($antes + 1)) "cola de muertos: $antes -> $despues"
}

# ---------- Resumen ----------

Titulo "Resumen"
$fallos = @($Resultados | Where-Object { -not $_.Ok })
Write-Host "Verificaciones: $($Resultados.Count). Fallos: $($fallos.Count)."
$fallos | ForEach-Object { Write-Host "  FALLO: $($_.Nombre)" }
if ($fallos.Count -gt 0) { exit 1 }

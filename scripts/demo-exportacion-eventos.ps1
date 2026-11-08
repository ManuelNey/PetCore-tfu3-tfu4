# Demo de la arquitectura basada en eventos (exportacion del historial a PDF).
#
# Requisitos: la aplicacion levantada con scripts\andis-up.ps1.
# Ejecutar:   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo-exportacion-eventos.ps1
#
# Muestra [OK] o [FALLO] por verificación. Si algo falla, termina con codigo distinto de 0.
#
# Sin parametros corre todo. Con -Demo prueba solo el caso normal y las caidas
# del worker, RabbitMQ y SOAP, para una presentacion corta.

param([switch]$Demo)

$ErrorActionPreference = "Continue"
$Api = "http://localhost:8000"
$Resultados = @()

# ---------- Utilidades ----------

function Registrar($nombre, $ok, $detalle) {
    $marca = if ($ok) { "[OK]   " } else { "[FALLO]" }
    Write-Host "$marca $nombre - $detalle"
    $script:Resultados += [pscustomobject]@{ Escenario = $nombre; Resultado = $(if ($ok) { "OK" } else { "FALLO" }); Detalle = $detalle }
}

function Titulo($texto) { Write-Host ""; Write-Host "=== $texto ===" -ForegroundColor Cyan }

function Llamar($metodo, $ruta, $token) {
    $cabeceras = @{}
    if ($token) { $cabeceras["Authorization"] = "Bearer $token" }
    try {
        $r = Invoke-WebRequest -Uri "$Api$ruta" -Method $metodo -Headers $cabeceras -UseBasicParsing -TimeoutSec 30
        $cuerpo = $r.Content
        # PowerShell 5.1 lee el JSON como Latin-1: se vuelve a decodificar como UTF-8 para ver bien las tildes.
        if ($r.Headers["Content-Type"] -like "*json*") {
            $cuerpo = [Text.Encoding]::UTF8.GetString([Text.Encoding]::GetEncoding(28591).GetBytes($cuerpo))
        }
        return [pscustomobject]@{ Estado = [int]$r.StatusCode; Cuerpo = $cuerpo; Tipo = $r.Headers["Content-Type"]; Bytes = $r.RawContentLength }
    } catch {
        $codigo = 0
        if ($_.Exception.Response) { $codigo = [int]$_.Exception.Response.StatusCode }
        return [pscustomobject]@{ Estado = $codigo; Cuerpo = $_.ErrorDetails.Message; Tipo = ""; Bytes = 0 }
    }
}

function Iniciar-Sesion($correo) {
    $cuerpo = @{ correo = $correo; contrasena = "Password123!" } | ConvertTo-Json
    $r = Invoke-RestMethod -Uri "$Api/auth/login" -Method Post -ContentType "application/json" -Body $cuerpo
    return $r.access_token
}

function Sql($consulta) {
    $salida = docker compose exec -T db psql -U postgres -d postgres -tA -c $consulta 2>$null
    return ($salida | Select-Object -First 1)
}

function Pedir-Exportacion($token, $idMascota = 1) {
    $r = Llamar "POST" "/historial/$idMascota/exportar" $token
    $id = $null
    if ($r.Estado -eq 202) { $id = ($r.Cuerpo | ConvertFrom-Json).id_tarea }
    return [pscustomobject]@{ Estado = $r.Estado; Id = $id }
}

function Estado-Tarea($token, $id) {
    $r = Llamar "GET" "/historial/exportar/$id" $token
    if ($r.Estado -ne 200) { return "?" }
    return ($r.Cuerpo | ConvertFrom-Json).estado
}

function Esperar-Estado($token, $id, $esperado, $segundos) {
    $limite = (Get-Date).AddSeconds($segundos)
    do {
        $e = Estado-Tarea $token $id
        if ($e -eq $esperado) { return $e }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $limite)
    return (Estado-Tarea $token $id)
}

function Esperar-Api($segundos = 60) {
    $limite = (Get-Date).AddSeconds($segundos)
    do {
        $r = Llamar "GET" "/health" $null
        if ($r.Estado -eq 200) { return $true }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $limite)
    return $false
}

function Reiniciar-Api {
    docker compose restart server | Out-Null
    # Recreamos Nginx para que encuentre las nuevas direcciones de las replicas.
    docker compose up -d --no-deps --force-recreate balanceador 2>&1 | Out-Null
    Esperar-Api | Out-Null
}

function Asegurar-Servicios {
    docker compose up -d rabbitmq historial-soap worker 2>&1 | Out-Null
    Esperar-Api | Out-Null
}

# ---------- Preparacion ----------

Titulo "Preparacion"
Asegurar-Servicios
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
$enlace = ((Llamar "GET" "/historial/exportar/$($t.Id)" $vet).Cuerpo | ConvertFrom-Json).enlace_descarga
$d = Llamar "GET" $enlace $null
Registrar "1c. El PDF se descarga sin login (Valet Key)" ($d.Estado -eq 200 -and $d.Tipo -like "*pdf*") "HTTP $($d.Estado), $($d.Tipo), $($d.Bytes) bytes"

# ---------- 2. Consulta REST via SOAP ----------
if (-not $Demo) {

Titulo "2. Consulta del historial: REST -> SOAP (WSDL en http://localhost:8001/soap/historial?wsdl)"
$r = Llamar "GET" "/mascotas/1/historial" $vet
Registrar "2a. Veterinario ve el historial" ($r.Estado -eq 200 -and $r.Cuerpo -like '*"consultas"*') "HTTP $($r.Estado)"
$r = Llamar "GET" "/mascotas/1/historial?limite=2" $cli
$n = ([regex]::Matches($r.Cuerpo, '"id_consulta"')).Count
Registrar "2b. Cliente ve su historial paginado (limite=2)" ($r.Estado -eq 200 -and $n -eq 2) "HTTP $($r.Estado), $n consultas"
$r = Llamar "GET" "/mascotas/1/historial" $adm
Registrar "2c. Administrador no tiene acceso" ($r.Estado -eq 403) "HTTP $($r.Estado)"
$r = Llamar "GET" "/mascotas/99999/historial" $vet
Registrar "2d. Mascota inexistente da 404" ($r.Estado -eq 404) "HTTP $($r.Estado)"
$w = Invoke-WebRequest -Uri "http://localhost:8001/soap/historial?wsdl" -UseBasicParsing
Registrar "2e. El servicio SOAP publica su WSDL" ($w.StatusCode -eq 200 -and $w.Content -like "*ObtenerHistorialMascota*") "HTTP $($w.StatusCode)"

}

# ---------- 3. Worker detenido y reiniciado ----------

Titulo "3. Worker detenido y reiniciado: las solicitudes aceptadas se conservan"
docker compose stop worker | Out-Null
$ids = @(1..3 | ForEach-Object { (Pedir-Exportacion $vet).Id })
Start-Sleep -Seconds 8
$pend = @($ids | Where-Object { (Estado-Tarea $vet $_) -eq "PENDIENTE" }).Count
Registrar "3a. Con el worker caido, las 3 solicitudes se aceptan y esperan" ($pend -eq 3) "$pend de 3 en PENDIENTE"
docker compose start worker | Out-Null
Start-Sleep -Seconds 5
$ok = @($ids | Where-Object { (Esperar-Estado $vet $_ "LISTO" 60) -eq "LISTO" }).Count
Registrar "3b. Al reiniciar el worker, se completan las 3" ($ok -eq 3) "$ok de 3 en LISTO"

# ---------- 4 y 5. API reiniciada y Outbox ----------
if (-not $Demo) {

Titulo "4. API reiniciada despues de aceptar la tarea"
docker compose stop worker | Out-Null
$t = Pedir-Exportacion $vet
Reiniciar-Api
$e1 = Estado-Tarea $vet $t.Id
Registrar "4a. Tras reiniciar la API, la tarea sigue registrada" ($e1 -eq "PENDIENTE") "estado: $e1"
docker compose start worker | Out-Null
$e = Esperar-Estado $vet $t.Id "LISTO" 60
Registrar "4b. Al volver el worker, la tarea se completa" ($e -eq "LISTO") "estado final: $e"

# ---------- 5. Outbox: la API cae antes de publicar ----------

Titulo "5. Outbox: tarea guardada pero evento sin publicar (la API cayo antes de publicarlo)"
# Se simula insertando la tarea directo en la base, con evento_publicado = FALSE.
$id = Sql "INSERT INTO tarea_exportacion (id_mascota, id_usuario, evento_publicado) VALUES (1, 2, FALSE) RETURNING id_tarea"
$id = $id.Trim()
$antes = Sql "SELECT evento_publicado FROM tarea_exportacion WHERE id_tarea = '$id'"
Registrar "5a. Tarea guardada con el evento sin publicar" ($antes.Trim() -eq "f") "evento_publicado = $($antes.Trim())"
$e = Esperar-Estado $vet $id "LISTO" 90
$despues = Sql "SELECT evento_publicado FROM tarea_exportacion WHERE id_tarea = '$id'"
Registrar "5b. El reenviador publica el evento y la tarea se completa" ($e -eq "LISTO" -and $despues.Trim() -eq "t") "estado: $e, evento_publicado = $($despues.Trim())"

}

# ---------- 6. RabbitMQ caido ----------

Titulo "6. RabbitMQ caido: la solicitud se acepta y se envia cuando vuelve"
docker compose stop rabbitmq | Out-Null
$t = Pedir-Exportacion $vet
Registrar "6a. Con RabbitMQ caido, la API igual acepta la solicitud" ($t.Estado -eq 202) "HTTP $($t.Estado)"
$pub = Sql "SELECT evento_publicado FROM tarea_exportacion WHERE id_tarea = '$($t.Id)'"
Registrar "6b. El evento queda pendiente de publicar" ($pub.Trim() -eq "f") "evento_publicado = $($pub.Trim())"
docker compose start rabbitmq | Out-Null
$e = Esperar-Estado $vet $t.Id "LISTO" 120
Registrar "6c. Al volver RabbitMQ, la tarea se completa" ($e -eq "LISTO") "estado final: $e"

# ---------- 7. Mensaje duplicado ----------
if (-not $Demo) {

Titulo "7. Mensaje duplicado: la misma solicitud llega dos veces"
$t = Pedir-Exportacion $vet
Esperar-Estado $vet $t.Id "LISTO" 60 | Out-Null
$archivo = "/app/exportaciones/$($t.Id).pdf"
$antes = (docker compose exec -T worker stat -c "%Y" $archivo 2>$null | Select-Object -First 1)
$codigo = @"
from app.mensajeria import eventos, rabbitmq
for _ in range(2):
    rabbitmq.publicar(eventos.RK_SOLICITADA, eventos.exportacion_solicitada('$($t.Id)', 1, 2))
"@
$codigo | docker compose exec -T worker uv run python - 2>&1 | Out-Null
Start-Sleep -Seconds 8
$despues = (docker compose exec -T worker stat -c "%Y" $archivo 2>$null | Select-Object -First 1)
$e = Estado-Tarea $vet $t.Id
Registrar "7. Dos solicitudes repetidas no regeneran el PDF" ($e -eq "LISTO" -and $antes -eq $despues) "estado: $e, fecha del archivo sin cambios: $($antes -eq $despues)"

}

# ---------- 8. SOAP caido ----------

Titulo "8. Servicio SOAP caido: reintentos limitados y error explicito"
docker compose stop historial-soap | Out-Null
$t = Pedir-Exportacion $vet
$e = Esperar-Estado $vet $t.Id "ERROR" 90
$detalle = ((Llamar "GET" "/historial/exportar/$($t.Id)" $vet).Cuerpo | ConvertFrom-Json).error
Registrar "8a. Tras agotar los reintentos, la tarea queda en ERROR (no pendiente para siempre)" ($e -eq "ERROR") "estado: $e, motivo: $detalle"
docker compose start historial-soap | Out-Null
Start-Sleep -Seconds 20
$t = Pedir-Exportacion $vet
$e = Esperar-Estado $vet $t.Id "LISTO" 60
Registrar "8b. Con el SOAP de vuelta, las exportaciones funcionan otra vez" ($e -eq "LISTO") "estado final: $e"

# ---------- 9. Mensaje invalido ----------
if (-not $Demo) {

Titulo "9. Mensaje invalido: va a la cola de mensajes muertos"
function Muertos { ((docker compose exec -T rabbitmq rabbitmqctl list_queues name messages 2>$null) | Where-Object { $_ -like "exportaciones.solicitadas.muertas*" }) -replace '.*\s', '' }
$antes = [int](Muertos)
$codigo = @"
from app.mensajeria import eventos, rabbitmq
con, can = rabbitmq.abrir_canal()
can.basic_publish(eventos.EXCHANGE, eventos.RK_SOLICITADA, b'esto no es json')
con.close()
"@
$codigo | docker compose exec -T worker uv run python - 2>&1 | Out-Null
Start-Sleep -Seconds 5
$despues = [int](Muertos)
Registrar "9. El mensaje invalido se aparta sin trabar al worker" ($despues -eq ($antes + 1)) "cola de muertos: $antes -> $despues"

}

# ---------- Resumen ----------

Titulo "Resumen"
$Resultados | Format-Table -AutoSize -Wrap | Out-String | Write-Host
$fallos = @($Resultados | Where-Object { $_.Resultado -eq "FALLO" }).Count
Write-Host "Escenarios: $($Resultados.Count). Fallos: $fallos."
if ($fallos -gt 0) { exit 1 }

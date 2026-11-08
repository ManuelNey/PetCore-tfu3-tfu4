# Mide que pasa con los PDF al frenar la API o el worker. Se corre una version por vez.
#
# La prueba es la misma en las dos versiones:
#   1. Pedimos las exportaciones y contamos cuantas acepta la API.
#   2. Frenamos el proceso que arma los PDF:
#        anterior -> las replicas de la API, que armaban los PDF
#        nueva    -> el worker
#      Sin -Ordenada corta de golpe con docker kill.
#      Con -Ordenada usa docker stop y deja terminar el trabajo en curso.
#   3. Al levantarlo, esperamos hasta EsperaMax segundos y contamos como quedaron las tareas.
#
# Correr desde la version que quieras medir, o indicar su carpeta con -Directorio:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\medir-interrupcion.ps1 -Arquitectura nueva
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\medir-interrupcion.ps1 -Arquitectura anterior -Directorio C:\ruta\a\la\version\anterior

param(
    [Parameter(Mandatory = $true)][ValidateSet("anterior", "nueva")][string]$Arquitectura,
    [string]$Directorio = ".",
    [int]$Solicitudes = 5,
    [int]$SegundosCaido = 10,
    [int]$EsperaMax = 90,
    [switch]$Ordenada
)

$ErrorActionPreference = "Continue"
Set-Location $Directorio
$Api = "http://localhost:8000"

function Llamar($metodo, $ruta, $token) {
    $cabeceras = @{}
    if ($token) { $cabeceras["Authorization"] = "Bearer $token" }
    try {
        $r = Invoke-WebRequest -Uri "$Api$ruta" -Method $metodo -Headers $cabeceras -UseBasicParsing -TimeoutSec 30
        return [pscustomobject]@{ Estado = [int]$r.StatusCode; Cuerpo = $r.Content }
    } catch {
        $codigo = 0
        if ($_.Exception.Response) { $codigo = [int]$_.Exception.Response.StatusCode }
        return [pscustomobject]@{ Estado = $codigo; Cuerpo = "" }
    }
}

function Esperar-Api {
    $limite = (Get-Date).AddSeconds(90)
    do {
        if ((Llamar "GET" "/health" $null).Estado -eq 200) { return }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $limite)
}

$cuerpoLogin = @{ correo = "bruno.vet@petcore.com"; contrasena = "contraSegura123" } | ConvertTo-Json
$token = (Invoke-RestMethod -Uri "$Api/auth/login" -Method Post -ContentType "application/json" -Body $cuerpoLogin).access_token

$forma = if ($Ordenada) { "apagado ordenado" } else { "caida abrupta" }
Write-Host "Arquitectura: $Arquitectura | Solicitudes: $Solicitudes | Componente caido: $SegundosCaido s ($forma)"

# 1. Pedir las exportaciones
$inicio = Get-Date
$ids = @()
$aceptadas = 0
for ($i = 1; $i -le $Solicitudes; $i++) {
    $r = Llamar "POST" "/historial/1/exportar" $token
    if ($r.Estado -eq 202) { $aceptadas++; $ids += ($r.Cuerpo | ConvertFrom-Json).id_tarea }
}
Write-Host "Aceptadas por la API: $aceptadas de $Solicitudes"

# 2. Frenar el proceso que arma los PDF
$accion = if ($Ordenada) { "stop" } else { "kill" }

if ($Arquitectura -eq "anterior") {
    Write-Host "Interrumpiendo las replicas de la API ($accion)..."
    docker compose $accion server 2>&1 | Out-Null
    Start-Sleep -Seconds $SegundosCaido
    docker compose start server 2>&1 | Out-Null
    docker compose up -d --no-deps --force-recreate balanceador 2>&1 | Out-Null
    Esperar-Api
} else {
    Write-Host "Interrumpiendo el worker ($accion)..."
    docker compose $accion worker 2>&1 | Out-Null
    Start-Sleep -Seconds $SegundosCaido
    docker compose start worker 2>&1 | Out-Null
}

# 3. Esperar y contar
$limite = (Get-Date).AddSeconds($EsperaMax)
$completadas = 0; $pendientes = $aceptadas; $errores = 0
$tiempoTotal = $null
do {
    Start-Sleep -Seconds 2
    $estados = @($ids | ForEach-Object {
        $r = Llamar "GET" "/historial/exportar/$_" $token
        if ($r.Estado -eq 200) { ($r.Cuerpo | ConvertFrom-Json).estado } else { "?" }
    })
    $completadas = @($estados | Where-Object { $_ -eq "LISTO" }).Count
    $errores = @($estados | Where-Object { $_ -eq "ERROR" }).Count
    $pendientes = $aceptadas - $completadas - $errores
    if ($pendientes -eq 0) { $tiempoTotal = [math]::Round(((Get-Date) - $inicio).TotalSeconds, 1); break }
} while ((Get-Date) -lt $limite)

Write-Host ""
Write-Host "RESULTADO ($Arquitectura)"
Write-Host "  Solicitudes enviadas : $Solicitudes"
Write-Host "  Aceptadas            : $aceptadas"
Write-Host "  Completadas (LISTO)  : $completadas"
Write-Host "  Con error            : $errores"
Write-Host "  Pendientes al final  : $pendientes"
if ($tiempoTotal) { Write-Host "  Tiempo hasta terminar: $tiempoTotal s" }
else { Write-Host "  Tiempo hasta terminar: no terminaron en $EsperaMax s" }

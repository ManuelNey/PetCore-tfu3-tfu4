$ErrorActionPreference = "Stop"

$baseUrl = "http://localhost:8000"

try {
    Write-Host "Preparando una sola replica para la demo de reintentos..."

    docker compose up -d --scale server=1 server

    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo dejar una sola replica de la API."
    }

    docker compose up -d --no-deps --force-recreate balanceador

    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo actualizar el balanceador."
    }

    Write-Host "Iniciando sesion..."

    $datosLogin = @{
        correo = "ana.cliente@petcore.com"
        contrasena = "contraSegura123"
    } | ConvertTo-Json

    $login = Invoke-RestMethod `
        -Method Post `
        -Uri "$baseUrl/auth/login" `
        -ContentType "application/json" `
        -Body $datosLogin `
        -TimeoutSec 5

    $encabezados = @{
        Authorization = "Bearer $($login.access_token)"
    }

    Write-Host "Configurando dos fallas simuladas..."

    $simulacion = Invoke-RestMethod `
        -Method Post `
        -Uri "$baseUrl/debug/simular-falla-conexion?veces=2" `
        -Headers $encabezados `
        -TimeoutSec 5

    Write-Host $simulacion.mensaje

    Write-Host "Ejecutando GET /mascotas..."

    $mascotas = Invoke-RestMethod `
        -Method Get `
        -Uri "$baseUrl/mascotas" `
        -Headers $encabezados `
        -TimeoutSec 10

    Write-Host "La operacion termino correctamente."
    Write-Host "Mascotas recibidas: $(@($mascotas).Count)"

    $resultado = Invoke-RestMethod `
        -Method Get `
        -Uri "$baseUrl/debug/ultimo-intento-conexion" `
        -Headers $encabezados `
        -TimeoutSec 5

    Write-Host ""
    Write-Host "Resultado de los reintentos:"
    Write-Host "Intentos usados: $($resultado.intentos_usados)"
    Write-Host "Duracion: $($resultado.duracion_segundos) segundos"
    Write-Host "Exitoso: $($resultado.exitoso)"

    if ($resultado.intentos_usados -ne 3) {
        throw "Se esperaban 3 intentos."
    }

    if ($resultado.exitoso -ne $true) {
        throw "La conexion no se recupero correctamente."
    }

    Write-Host ""
    Write-Host "Demostracion de reintentos exitosa."
}
finally {
    Write-Host ""
    Write-Host "Restaurando las dos replicas..."

    docker compose up -d --scale server=2 server

    if ($LASTEXITCODE -ne 0) {
        Write-Warning "No se pudieron restaurar las dos replicas."
    }

    docker compose up -d --no-deps --force-recreate balanceador

    if ($LASTEXITCODE -ne 0) {
        Write-Warning "No se pudo actualizar el balanceador."
    }

    docker compose ps
}

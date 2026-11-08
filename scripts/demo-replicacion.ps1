$ErrorActionPreference = "Stop"

Write-Host "Comprobando las replicas disponibles..."

$replicas = @(
    docker compose ps -q server
)

if ($replicas.Count -lt 2) {
    throw "La demostracion necesita dos replicas de la API."
}

Write-Host "Iniciando sesion para acceder al endpoint protegido..."

$datosLogin = @{
    correo = "ana.cliente@petcore.com"
    contrasena = "contraSegura123"
} | ConvertTo-Json

$login = Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:8000/auth/login" `
    -ContentType "application/json" `
    -Body $datosLogin `
    -TimeoutSec 5

$encabezados = @{
    Authorization = "Bearer $($login.access_token)"
}

Write-Host ""
Write-Host "Solicitudes antes de la falla:"

for ($i = 1; $i -le 6; $i++) {
    $respuesta = Invoke-RestMethod `
        -Uri "http://localhost:8000/demo/instancia" `
        -Headers $encabezados `
        -TimeoutSec 3

    Write-Host "Solicitud $i atendida por $($respuesta.instancia)"
}

$replicaDetenida = $replicas[0]

$nombreReplica = docker inspect `
    --format "{{.Name}}" `
    $replicaDetenida

$nombreReplica = $nombreReplica.TrimStart("/")

Write-Host ""
Write-Host "Deteniendo la replica $nombreReplica..."

docker stop $replicaDetenida

if ($LASTEXITCODE -ne 0) {
    throw "No se pudo detener la replica."
}

Write-Host ""
Write-Host "Solicitudes despues de la falla:"

for ($i = 1; $i -le 10; $i++) {
    $respuesta = Invoke-RestMethod `
        -Uri "http://localhost:8000/demo/instancia" `
        -Headers $encabezados `
        -TimeoutSec 3

    Write-Host "Solicitud $i atendida por $($respuesta.instancia)"
}

Write-Host ""
Write-Host "El servicio continuo disponible."
Write-Host "Recuperando la segunda replica..."

docker compose up -d --scale server=2 server

if ($LASTEXITCODE -ne 0) {
    throw "No se pudo recuperar la segunda replica."
}

docker compose up -d --no-deps --force-recreate balanceador

if ($LASTEXITCODE -ne 0) {
    throw "No se pudo actualizar el balanceador."
}

Write-Host ""
Write-Host "Demostracion terminada. Las dos replicas fueron restauradas."

docker compose ps

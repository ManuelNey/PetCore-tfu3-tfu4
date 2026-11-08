$ErrorActionPreference = "Stop"

$baseUrl = "http://localhost:8000"
$contrasena = "contraSegura123"

function Iniciar-Sesion {
    param(
        [string]$Correo
    )

    $datosLogin = @{
        correo = $Correo
        contrasena = $contrasena
    } | ConvertTo-Json

    return Invoke-RestMethod `
        -Method Post `
        -Uri "$baseUrl/auth/login" `
        -ContentType "application/json" `
        -Body $datosLogin `
        -TimeoutSec 5
}

Write-Host "Iniciando sesion como cliente..."

$loginCliente = Iniciar-Sesion `
    -Correo "ana.cliente@petcore.com"

$encabezadosCliente = @{
    Authorization = "Bearer $($loginCliente.access_token)"
}

Write-Host "El cliente intenta acceder a GET /agenda..."

$codigoCliente = 0

try {
    $respuestaCliente = Invoke-WebRequest `
        -UseBasicParsing `
        -Method Get `
        -Uri "$baseUrl/agenda" `
        -Headers $encabezadosCliente `
        -TimeoutSec 5

    $codigoCliente = [int]$respuestaCliente.StatusCode
}
catch {
    if ($null -eq $_.Exception.Response) {
        throw
    }

    $codigoCliente = [int]$_.Exception.Response.StatusCode
}

Write-Host "Estado para el cliente: $codigoCliente"

if ($codigoCliente -ne 403) {
    throw "Se esperaba 403 para el cliente sin permiso."
}

Write-Host "Iniciando sesion como veterinario..."

$loginVeterinario = Iniciar-Sesion `
    -Correo "bruno.vet@petcore.com"

$encabezadosVeterinario = @{
    Authorization = "Bearer $($loginVeterinario.access_token)"
}

$respuestaVeterinario = Invoke-WebRequest `
    -UseBasicParsing `
    -Method Get `
    -Uri "$baseUrl/agenda" `
    -Headers $encabezadosVeterinario `
    -TimeoutSec 5

$codigoVeterinario = [int]$respuestaVeterinario.StatusCode

Write-Host "Estado para el veterinario: $codigoVeterinario"

if ($codigoVeterinario -ne 200) {
    throw "Se esperaba 200 para el veterinario autorizado."
}

Write-Host ""
Write-Host "Demostracion de autorizacion exitosa."
Write-Host "Cliente: 403 Forbidden"
Write-Host "Veterinario: 200 OK"

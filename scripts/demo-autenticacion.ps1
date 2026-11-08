$ErrorActionPreference = "Stop"

$baseUrl = "http://localhost:8000"

Write-Host "Intentando acceder sin iniciar sesion..."

$codigoSinToken = 0

try {
    $respuestaSinToken = Invoke-WebRequest `
        -UseBasicParsing `
        -Method Get `
        -Uri "$baseUrl/mascotas" `
        -TimeoutSec 5

    $codigoSinToken = [int]$respuestaSinToken.StatusCode
}
catch {
    if ($null -eq $_.Exception.Response) {
        throw
    }

    $codigoSinToken = [int]$_.Exception.Response.StatusCode
}

Write-Host "Estado sin token: $codigoSinToken"

if ($codigoSinToken -ne 401) {
    throw "Se esperaba 401 para el acceso sin autenticar."
}

Write-Host "Iniciando sesion como cliente..."

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

$respuestaAutenticada = Invoke-WebRequest `
    -UseBasicParsing `
    -Method Get `
    -Uri "$baseUrl/mascotas" `
    -Headers $encabezados `
    -TimeoutSec 5

$codigoAutenticado = [int]$respuestaAutenticada.StatusCode

Write-Host "Estado con token: $codigoAutenticado"

if ($codigoAutenticado -ne 200) {
    throw "Se esperaba 200 para el usuario autenticado."
}

Write-Host ""
Write-Host "Demostracion de autenticacion exitosa."
Write-Host "Sin token: 401 Unauthorized"
Write-Host "Con token: 200 OK"

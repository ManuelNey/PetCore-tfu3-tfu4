$ErrorActionPreference = "Stop"

Write-Host "Construyendo y levantando PostgreSQL, Redis, RabbitMQ, dos replicas de la API y el worker..."

# rabbitmq y worker: sin el worker las exportaciones del historial quedan PENDIENTE para siempre.
docker compose up --build -d --scale server=2 db redis rabbitmq server worker

if ($LASTEXITCODE -ne 0) {
    throw "No se pudieron levantar PostgreSQL, Redis, RabbitMQ, las replicas de la API y el worker."
}

Write-Host "Actualizando el balanceador..."

docker compose up -d --no-deps --force-recreate balanceador
docker compose up --build -d --no-deps --force-recreate balanceador

if ($LASTEXITCODE -ne 0) {
    throw "No se pudo iniciar el balanceador."
}

Write-Host ""
Write-Host "API iniciada con dos replicas, cache Redis y worker de exportaciones (RabbitMQ)."
Write-Host "Consola de RabbitMQ: http://localhost:15672 (usuario y clave: petcore)"
Write-Host "API: http://localhost:8000"
Write-Host "Documentacion: http://localhost:8000/docs"
Write-Host ""

Write-Host "Comprobando Redis..."

docker compose exec -T redis redis-cli ping

if ($LASTEXITCODE -ne 0) {
    throw "Redis no esta respondiendo."
}

Write-Host ""
Write-Host "Contenedores utilizados por la demo:"

docker compose ps db redis rabbitmq server worker balanceador
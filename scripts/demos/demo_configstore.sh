#!/usr/bin/env bash
# Demo 4: External Configuration Store
# Correr desde la raiz del repo.

set -u
BASE="http://localhost:8000"

step() {
  echo ""
  echo "=================================================================="
  echo "  $1"
  echo "=================================================================="
  read -p "  (Enter para ejecutar) " _
}

step "1) Login como administrador"
ADMINTOKEN=$(curl -s -X POST "$BASE/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"correo":"carla.admin@petcore.com","contrasena":"contraSegura123"}' \
  | python -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")
echo "  token obtenido (${#ADMINTOKEN} caracteres)"

step "2) Consulto el limite actual (deberia ser 5)"
curl -s "$BASE/admin/configuracion/LOGIN_MAX_INTENTOS" -H "Authorization: Bearer $ADMINTOKEN"
echo ""

step "3) Registro una cuenta de prueba nueva (correo aleatorio, para que la demo sea repetible)"
RAND=$RANDOM
CORREO="demo${RAND}@petcore.com"
curl -s -w "\nstatus: %{http_code}\n" -X POST "$BASE/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"nombre\":\"Demo\",\"apellido\":\"Config\",\"documento\":\"$RAND\",\"correo\":\"$CORREO\",\"contrasena\":\"contraSegura123\",\"confirmar_contrasena\":\"contraSegura123\",\"telefono\":\"099123456\"}"
echo "  correo de prueba: $CORREO"

step "4) Cambio el limite a 3, sin reiniciar nada (PUT /admin/configuracion)"
curl -s -w "\nstatus: %{http_code}\n" -X PUT "$BASE/admin/configuracion/LOGIN_MAX_INTENTOS" \
  -H "Authorization: Bearer $ADMINTOKEN" -H "Content-Type: application/json" \
  -d '{"valor":"3"}'

step "5) Tres logins fallidos seguidos con el nuevo limite -> el tercero bloquea la cuenta"
for i in 1 2 3; do
  echo "  intento $i:"
  curl -s -w "   status: %{http_code}\n" -X POST "$BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"correo\":\"$CORREO\",\"contrasena\":\"incorrecta\"}"
done

step "6) Intento con la contrasena CORRECTA -> deberia seguir bloqueada"
curl -s -w "\nstatus: %{http_code}\n" -X POST "$BASE/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"correo\":\"$CORREO\",\"contrasena\":\"contraSegura123\"}"

step "7) Restauro el limite a 5"
curl -s -w "\nstatus: %{http_code}\n" -X PUT "$BASE/admin/configuracion/LOGIN_MAX_INTENTOS" \
  -H "Authorization: Bearer $ADMINTOKEN" -H "Content-Type: application/json" \
  -d '{"valor":"5"}'

echo ""
echo "Demo de External Configuration Store terminada."

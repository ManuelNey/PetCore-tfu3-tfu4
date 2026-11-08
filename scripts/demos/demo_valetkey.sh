#!/usr/bin/env bash
# Demo 3: Asynchronous Request-Reply + Valet Key
# Correr desde la raiz del repo.

set -u
BASE="http://localhost:8000"
ID_MASCOTA=1

step() {
  echo ""
  echo "=================================================================="
  echo "  $1"
  echo "=================================================================="
  read -p "  (Enter para ejecutar) " _
}

step "1) Login como veterinario"
VETTOKEN=$(curl -s -X POST "$BASE/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"correo":"bruno.vet@petcore.com","contrasena":"contraSegura123"}' \
  | python -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")
echo "  token obtenido (${#VETTOKEN} caracteres)"

step "2) POST /historial/$ID_MASCOTA/exportar -> debe responder 202 al instante"
RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/historial/$ID_MASCOTA/exportar" \
  -H "Authorization: Bearer $VETTOKEN")
echo "$RESP"
ID_TAREA=$(echo "$RESP" | head -n1 | python -c "import sys,json; print(json.load(sys.stdin).get('id_tarea',''))")
echo "  id_tarea = $ID_TAREA"

step "3) Mientras tanto, otra request cualquiera sigue respondiendo normal (la API no esta bloqueada)"
curl -s -o /dev/null -w "GET /demo/instancia -> status: %{http_code}\n" \
  -H "Authorization: Bearer $VETTOKEN" "$BASE/demo/instancia"

step "4) Polling del estado hasta que de LISTO"
ENLACE=""
for i in 1 2 3 4 5 6; do
  OUT=$(curl -s "$BASE/historial/exportar/$ID_TAREA" -H "Authorization: Bearer $VETTOKEN")
  echo "  intento $i: $OUT"
  ESTADO=$(echo "$OUT" | python -c "import sys,json; print(json.load(sys.stdin).get('estado',''))")
  if [ "$ESTADO" = "LISTO" ]; then
    ENLACE=$(echo "$OUT" | python -c "import sys,json; print(json.load(sys.stdin).get('enlace_descarga',''))")
    break
  fi
  sleep 2
done

step "5) Descargo el PDF con el enlace, SIN mandar ningun token de login"
curl -s -o /tmp/historial_demo.pdf -w "status: %{http_code}  content-type: %{content_type}\n" \
  "$BASE$ENLACE"
echo "  PDF guardado en /tmp/historial_demo.pdf"

step "6) Uso un token invalido a proposito -> debe rechazar"
curl -s -o /dev/null -w "status: %{http_code}\n" \
  "$BASE/historial/exportar/$ID_TAREA/descargar?token=tokeninvalido123"

echo ""
echo "Demo de Valet Key terminada."

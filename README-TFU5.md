# Pet-Core: servicio SOAP de historial clínico

## Qué se implementó

Se separó la consulta del historial clínico en una aplicación SOAP ubicada en la carpeta `SOAP`, con su propio proceso y contenedor Docker, llamado `historial-soap`.

La API REST continúa atendiendo las operaciones existentes, incluido el inicio de sesión. La aplicación SOAP expone la consulta del historial mediante mensajes XML y publica su contrato WSDL.


## Seguridad y reglas de negocio

Se reutilizó el middleware JWT de la API original. El usuario inicia sesión en la API REST y envía el access token obtenido al servicio SOAP mediante el encabezado `Authorization: Bearer TOKEN`.

SOAP valida la firma, el vencimiento, el issuer, la audience y los claims requeridos, utilizando la misma clave JWT configurada mediante el secreto de Docker. No se creó otro sistema de login.


## Cómo levantar el servicio

Para construir y levantar todos los servicios:

```powershell
docker compose up -d --build
```

## Prueba manual con Postman

### 1. Iniciar sesión en la API REST

**POST** `http://localhost:8000/auth/login`

Copiar el valor de `access_token` de la respuesta.

### 2. Obtener el identificador de la mascota

**GET** `http://localhost:8000/mascotas`

En **Authorization → Bearer Token**, pegar el token. La solicitud no lleva body.

Elegir el perro de la respuesta y copiar su `id_mascota`. Para ver contenido clínico, utilizar una mascota que ya tenga consultas registradas.

### 3. Consultar el historial mediante SOAP/XML

**POST** `http://localhost:8001/soap/historial`

En **Authorization → Bearer Token**, pegar el mismo token.

Configurar estos encabezados:

| Encabezado | Valor |
|---|---|
| `Content-Type` | `text/xml; charset=utf-8` |
| `SOAPAction` | `"urn:petcore:historial/ObtenerHistorialMascota"` |

En **Body → raw → XML**, enviar el siguiente mensaje, reemplazando `1` por el identificador de la mascota:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope
    xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:h="urn:petcore:historial">
  <soap:Body>
    <h:ObtenerHistorialMascota>
      <h:id_mascota>1</h:id_mascota>
      <h:limite>10</h:limite>
      <h:offset>0</h:offset>
    </h:ObtenerHistorialMascota>
  </soap:Body>
</soap:Envelope>
```

### 4. Consultar el contrato WSDL y la salud

**GET** `http://localhost:8001/soap/historial?wsdl`

Devuelve el contrato XML con la operación, sus parámetros, los tipos de respuesta y la dirección del servicio. No requiere token.

**GET** `http://localhost:8001/health`

Comprueba el acceso a PostgreSQL. La respuesta esperada cuando está disponible es:

```json
{"status": "ok"}
```
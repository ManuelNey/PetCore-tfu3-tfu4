import jwt

from fastapi import (
    Depends,
    HTTPException,
    Request,
    Security,
    status,
)
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings


ALGORITMO_JWT = "HS256"

ROLES_VALIDOS = {
    "ADMINISTRADOR",
    "CLIENTE",
    "VETERINARIO",
}

bearer_scheme = HTTPBearer(auto_error=False)


class JWTMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.usuario = None
        request.state.error_autenticacion = None

        authorization = request.headers.get(
            "Authorization"
        )

        # Las rutas públicas pueden continuar sin token.
        if authorization is None:
            return await call_next(request)

        partes = authorization.split()

        if (
            len(partes) != 2
            or partes[0].lower() != "bearer"
        ):
            request.state.error_autenticacion = (
                "El encabezado de autorización no es válido."
            )

            return await call_next(request)

        token = partes[1]

        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[ALGORITMO_JWT],
                audience="pet-core-client",
                issuer="pet-core-api",
                options={
                    "require": [
                        "sub",
                        "rol",
                        "type",
                        "iss",
                        "aud",
                        "iat",
                        "nbf",
                        "exp",
                        "jti",
                    ]
                },
            )

            if payload["type"] != "access":
                raise jwt.InvalidTokenError(
                    "Tipo de token incorrecto."
                )

            id_usuario = int(payload["sub"])
            rol = str(payload["rol"]).upper()

            if id_usuario <= 0:
                raise jwt.InvalidTokenError(
                    "Identificador incorrecto."
                )

            if rol not in ROLES_VALIDOS:
                raise jwt.InvalidTokenError(
                    "Rol incorrecto."
                )

            request.state.usuario = {
                "id_usuario": id_usuario,
                "rol": rol,
                "jti": payload["jti"],
            }

        except jwt.ExpiredSignatureError:
            request.state.error_autenticacion = (
                "El token ha expirado."
            )

        except (
            jwt.InvalidTokenError,
            TypeError,
            ValueError,
        ):
            request.state.error_autenticacion = (
                "El token no es válido."
            )

        return await call_next(request)


def obtener_usuario_actual(
    request: Request,
    _credenciales: (
        HTTPAuthorizationCredentials | None
    ) = Security(bearer_scheme),
) -> dict:
    error = request.state.error_autenticacion

    if error is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error,
            headers={
                "WWW-Authenticate": "Bearer",
            },
        )

    usuario = request.state.usuario

    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere iniciar sesión.",
            headers={
                "WWW-Authenticate": "Bearer",
            },
        )

    return usuario


def requerir_rol(*roles_permitidos: str):
    roles_normalizados = {
        rol.upper()
        for rol in roles_permitidos
    }

    roles_desconocidos = (
        roles_normalizados - ROLES_VALIDOS
    )

    if len(roles_desconocidos) > 0:
        raise ValueError(
            "Se configuraron roles desconocidos: "
            + ", ".join(roles_desconocidos)
        )

    def verificar_rol(
        usuario: dict = Depends(
            obtener_usuario_actual
        ),
    ) -> dict:
        if usuario["rol"] not in roles_normalizados:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "No tiene permisos para acceder "
                    "a este recurso."
                ),
            )

        return usuario

    return verificar_rol
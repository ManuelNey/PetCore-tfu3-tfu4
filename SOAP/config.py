import os
from typing import Any

from pydantic import (
    Field,
    PostgresDsn,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # PostgreSQL
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str | None = None
    POSTGRES_PASSWORD_FILE: str | None = None
    POSTGRES_DB: str

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    CACHE_TTL_SECONDS: int = Field(
        default=300,
        ge=1,
    )

    # JWT
    JWT_SECRET_KEY: str = Field(
        min_length=32,
    )

    JWT_SECRET_KEY_FILE: str | None = None

    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=15,
        ge=5,
        le=60,
    )

    # Seguridad del login
    LOGIN_MAX_INTENTOS: int = Field(
        default=5,
        ge=3,
        le=10,
    )

    LOGIN_BLOQUEO_MINUTOS: int = Field(
        default=15,
        ge=1,
        le=1440,
    )

    # Exportación del historial a PDF
    # Carpeta donde se guardan los PDF.
    EXPORTACIONES_DIR: str = "/app/exportaciones"

    # Pausa antes de generar el PDF, solo para la demo (así se alcanza a ver el
    # estado PENDIENTE). En un uso real debe ser 0.
    EXPORTACION_RETARDO_SEGUNDOS: float = 0

    # Cuántos segundos dura el enlace de descarga (Valet Key). 600 = 10 minutos.
    VALET_KEY_SEGUNDOS: int = 600

    @model_validator(mode="before")
    @classmethod
    def check_postgres_password(
        cls,
        data: Any,
    ) -> Any:
        """
        Verifica que se proporcione la contraseña de PostgreSQL
        directamente o mediante un archivo secreto.
        """
        if isinstance(data, dict):
            password_file = data.get(
                "POSTGRES_PASSWORD_FILE"
            )

            password = data.get(
                "POSTGRES_PASSWORD"
            )

            if password_file is None and password is None:
                raise ValueError(
                    "POSTGRES_PASSWORD o "
                    "POSTGRES_PASSWORD_FILE "
                    "debe estar configurado."
                )

        return data

    @field_validator(
        "POSTGRES_PASSWORD_FILE",
        mode="before",
    )
    @classmethod
    def read_password_from_file(
        cls,
        value: str | None,
    ) -> str | None:
        """
        Si se proporciona POSTGRES_PASSWORD_FILE,
        reemplaza la ruta por el contenido del archivo.
        """
        if value is None:
            return None

        if not os.path.exists(value):
            raise ValueError(
                f"El archivo {value} no existe."
            )

        with open(
            value,
            encoding="utf-8",
        ) as file:
            password = file.read().strip()

        if password == "":
            raise ValueError(
                "El archivo de contraseña "
                "de PostgreSQL está vacío."
            )

        return password

    @model_validator(mode="before")
    @classmethod
    def read_jwt_secret(
        cls,
        data: Any,
    ) -> Any:
        """
        Lee la clave JWT desde JWT_SECRET_KEY o desde
        el archivo indicado en JWT_SECRET_KEY_FILE.
        """
        if not isinstance(data, dict):
            return data

        jwt_secret = data.get(
            "JWT_SECRET_KEY"
        )

        jwt_secret_file = data.get(
            "JWT_SECRET_KEY_FILE"
        )

        if jwt_secret is None and jwt_secret_file is None:
            raise ValueError(
                "JWT_SECRET_KEY o JWT_SECRET_KEY_FILE "
                "debe estar configurado."
            )

        if jwt_secret is None:
            if not os.path.exists(jwt_secret_file):
                raise ValueError(
                    f"El archivo {jwt_secret_file} "
                    "no existe."
                )

            with open(
                jwt_secret_file,
                encoding="utf-8",
            ) as file:
                jwt_secret = file.read().strip()

            if jwt_secret == "":
                raise ValueError(
                    "El archivo con la clave JWT "
                    "está vacío."
                )

            data["JWT_SECRET_KEY"] = jwt_secret

        return data

    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(
        self,
    ) -> PostgresDsn:
        password = (
            self.POSTGRES_PASSWORD
            if self.POSTGRES_PASSWORD
            else self.POSTGRES_PASSWORD_FILE
        )

        url = MultiHostUrl.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=password,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

        return PostgresDsn(url)


settings = Settings()  # type: ignore
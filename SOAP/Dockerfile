FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir uv==0.12.5

COPY pyproject.toml uv.lock ./

RUN uv sync --locked

# Tomamos de app/ el código que comparte con la API.
COPY app/config.py app/database.py ./app/
COPY app/Middleware/ ./app/Middleware/
COPY app/historial/repository.py app/historial/dto.py ./app/historial/

# Archivos propios del SOAP.
COPY SOAP/main.py ./app/main.py
COPY SOAP/distribuido/ ./app/distribuido/
COPY SOAP/historial/service.py ./app/historial/service.py

EXPOSE 8001

CMD ["uv", "run", "--locked", "python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]

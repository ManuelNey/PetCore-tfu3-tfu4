FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir uv==0.12.5

COPY pyproject.toml uv.lock ./

RUN uv sync --locked

COPY SOAP/ ./app/

EXPOSE 8001

CMD ["uv", "run", "--locked", "python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
ARG DOCKER_REGISTRY_PREFIX=
FROM ${DOCKER_REGISTRY_PREFIX}library/python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

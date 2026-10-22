ARG DOCKER_REGISTRY_PREFIX=
FROM ${DOCKER_REGISTRY_PREFIX}library/python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml ./
RUN python -c 'import pathlib, tomllib; deps = tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["dependencies"]; pathlib.Path("requirements-docker.txt").write_text("\n".join(deps) + "\n")' \
    && pip install --no-cache-dir -r requirements-docker.txt
COPY backend/app ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

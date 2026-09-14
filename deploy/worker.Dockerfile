ARG DOCKER_REGISTRY_PREFIX=
FROM ${DOCKER_REGISTRY_PREFIX}library/python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY worker/pyproject.toml ./
COPY worker ./worker
RUN pip install --no-cache-dir .
CMD ["celery", "-A", "worker.tasks:app", "worker", "--loglevel=INFO"]

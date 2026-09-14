ARG DOCKER_REGISTRY_PREFIX=
FROM ${DOCKER_REGISTRY_PREFIX}library/node:22-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ${DOCKER_REGISTRY_PREFIX}library/nginx:1.27-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

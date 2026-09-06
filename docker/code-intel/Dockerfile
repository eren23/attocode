# The image installs only the standalone intelligence distribution.
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git curl libgit2-dev npm && rm -rf /var/lib/apt/lists/*
RUN npm install -g pyright typescript-language-server typescript && npm cache clean --force
COPY packages/code-intel/ /build/code-intel/
ARG ATTOCODE_INTEL_EXTRAS=service
RUN pip install --no-cache-dir "/build/code-intel[${ATTOCODE_INTEL_EXTRAS}]"
COPY --from=frontend /frontend/dist /app/static
RUN mkdir -p /var/lib/code-intel/repos
EXPOSE 8080
ENV ATTOCODE_HOST=0.0.0.0 ATTOCODE_PORT=8080 ATTOCODE_STATIC_DIR=/app/static
CMD ["attocode-code-intel", "serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]

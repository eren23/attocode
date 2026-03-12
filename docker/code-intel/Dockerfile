# Stage 1: Build frontend
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY frontend/ .
RUN npm run build

# Stage 2: Python application
FROM python:3.12-slim

WORKDIR /app

# Install git, libgit2, and curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl libgit2-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install with service extras (includes code-intel + all service deps)
RUN pip install --no-cache-dir ".[service]"

# Copy frontend build output
COPY --from=frontend /frontend/dist /app/static

# Create repo clone directory
RUN mkdir -p /var/lib/code-intel/repos

# Default port
EXPOSE 8080

# Run HTTP server
ENV ATTOCODE_HOST=0.0.0.0
ENV ATTOCODE_PORT=8080
ENV ATTOCODE_STATIC_DIR=/app/static

CMD ["attocode-code-intel", "serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]

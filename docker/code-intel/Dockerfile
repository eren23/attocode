# Stage 1: Build frontend
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY frontend/ .
RUN npm run build

# Stage 2: Install Python dependencies (cached unless pyproject.toml changes)
FROM python:3.12-slim AS deps

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git libgit2-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
# Minimal src layout so pip install can resolve the package
RUN mkdir -p src/attocode && touch src/attocode/__init__.py
RUN pip install --no-cache-dir ".[service,semantic]"

# Stage 3: Final image — copy installed deps + actual source
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl libgit2-dev npm && \
    rm -rf /var/lib/apt/lists/*

# Install language server binaries for LSP support
RUN npm install -g pyright typescript-language-server typescript && \
    npm cache clean --force

# Copy installed Python packages from deps stage
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy project source (changes here don't re-run pip install)
COPY pyproject.toml README.md ./
COPY src/ src/
# Re-install in editable-like mode (fast — deps already present, just registers the package)
RUN pip install --no-cache-dir --no-deps ".[service,semantic]"

# Copy frontend build output
COPY --from=frontend /frontend/dist /app/static

# Create repo clone directory
RUN mkdir -p /var/lib/code-intel/repos

EXPOSE 8080

ENV ATTOCODE_HOST=0.0.0.0
ENV ATTOCODE_PORT=8080
ENV ATTOCODE_STATIC_DIR=/app/static

CMD ["attocode-code-intel", "serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]

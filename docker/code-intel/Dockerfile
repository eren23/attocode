FROM python:3.12-slim

WORKDIR /app

# Install git for repo cloning (Phase 2)
RUN apt-get update && apt-get install -y --no-install-recommends git curl && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install with code-intel extras
RUN pip install --no-cache-dir ".[code-intel]"

# Default port
EXPOSE 8080

# Run HTTP server
ENV ATTOCODE_HOST=0.0.0.0
ENV ATTOCODE_PORT=8080

CMD ["attocode-code-intel", "serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]

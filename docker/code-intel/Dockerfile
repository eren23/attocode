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

# Create repo clone directory
RUN mkdir -p /var/lib/code-intel/repos

# Default port
EXPOSE 8080

# Run HTTP server
ENV ATTOCODE_HOST=0.0.0.0
ENV ATTOCODE_PORT=8080

CMD ["attocode-code-intel", "serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]

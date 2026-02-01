# Attocode Evaluation Framework
# Docker image for running SWE-bench and other evaluations

FROM node:20-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create Python venv to avoid pip externally-managed-environment error
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies for SWE-bench
# Using --no-cache-dir to reduce image size
RUN pip install --no-cache-dir \
    datasets \
    pandas \
    numpy

# Set working directory to project root
WORKDIR /app

# Copy package files first (for layer caching)
COPY package*.json ./

# Install Node dependencies
RUN npm ci

# Copy source code
COPY . .

# Build TypeScript
RUN npm run build

# Create directories that will be mounted
RUN mkdir -p .traces tools/eval/results

# Set environment variables
ENV NODE_ENV=production
ENV TRACE_OUTPUT_DIR=/app/.traces

# Default: show help
CMD ["npx", "tsx", "tools/eval/src/cli.ts", "--help"]

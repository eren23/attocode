# Attocode Evaluation Framework
# Docker image for running SWE-bench and other evaluations

FROM node:20-slim

# deps-v2: build-essential, python3-dev, gfortran for compiling C/Fortran extensions
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    gfortran \
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
    numpy \
    pytest \
    pytest-xdist \
    'setuptools<70' \
    wheel \
    Cython \
    swebench \
    setuptools_scm \
    extension-helpers \
    oldest-supported-numpy

# Enable legacy editable installs for setuptools<70 (PEP 660 compat)
ENV SETUPTOOLS_ENABLE_FEATURES="legacy-editable"

# Set working directory to project root
WORKDIR /app

# Copy package files first (for layer caching)
COPY package*.json ./

# Install Node dependencies
RUN npm ci

# Copy source code
COPY . .

# Install trace-dashboard dependencies (separate package)
RUN cd tools/trace-dashboard && npm ci

# Build TypeScript
RUN npm run build

# Create directories that will be mounted
RUN mkdir -p .traces tools/eval/results

# Set environment variables
ENV NODE_ENV=production
ENV TRACE_OUTPUT_DIR=/app/.traces

# Default: show help
CMD ["npm", "run", "eval", "--", "--help"]

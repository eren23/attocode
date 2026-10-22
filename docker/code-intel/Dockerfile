# The image installs only the standalone intelligence distribution.
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim AS runtime-base
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git curl libgit2-dev npm && rm -rf /var/lib/apt/lists/*
RUN npm install -g pyright typescript-language-server typescript && npm cache clean --force

FROM runtime-base AS context-check
COPY . /context/
RUN python - <<'PY'
from pathlib import Path
root = Path('/context')
allowed = {'frontend/package.json', 'frontend/package-lock.json', 'frontend/tsconfig.json',
           'frontend/vite.config.ts', 'frontend/index.html', 'packages/code-intel/pyproject.toml',
           'packages/code-intel/README.md', 'packages/code-intel/LICENSE'}
prefixes = ('frontend/src/', 'frontend/public/', 'packages/code-intel/src/')
for path in root.rglob('*'):
    if path.is_file():
        name = path.relative_to(root).as_posix()
        assert name in allowed or name.startswith(prefixes), f'unexpected build context input: {name}'
        assert not {'__pycache__', 'node_modules', '.attocode', '.venv', '.git'}.intersection(path.parts), name
        assert path.name != '.env' and not path.name.startswith('.env.') and path.suffix != '.pyc', name
for name in ('frontend/package.json', 'frontend/index.html', 'packages/code-intel/pyproject.toml',
             'packages/code-intel/src/attocode_intel/__init__.py'):
    assert (root / name).is_file(), f'required build context input missing: {name}'
PY

FROM runtime-base AS package-build
COPY packages/code-intel/ /build/code-intel/
ARG ATTOCODE_INTEL_EXTRAS=service
RUN pip install --no-cache-dir --no-compile --ignore-installed --prefix=/install "/build/code-intel[${ATTOCODE_INTEL_EXTRAS}]"

FROM runtime-base
COPY --from=package-build /install/ /usr/local/
COPY --from=frontend /frontend/dist /app/static
RUN mkdir -p /var/lib/code-intel/repos
EXPOSE 8080
ENV ATTOCODE_HOST=0.0.0.0 ATTOCODE_PORT=8080 ATTOCODE_STATIC_DIR=/app/static
CMD ["attocode-code-intel", "serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]

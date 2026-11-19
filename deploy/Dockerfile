# BMTL / ScrapTrust production image (build from the repository root):
#   docker build -f deploy/Dockerfile -t bmtl:2026.11 .
# Hardening: multi-stage, pinned base images, non-root user, no compilers or source maps in the final image,
# models fetched and checksum-verified at BUILD time (ALLOW_MODEL_DOWNLOADS=false at run time),
# code and models read-only; only /data is writable.

# ---------- 1. web app (static files only end up in the final image)
FROM node:22.11-bookworm-slim AS web
WORKDIR /web
COPY app/package.json app/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY app/index.html app/vite.config.js app/tsconfig.json ./
COPY app/src ./src
RUN npx tsc --noEmit && npx vite build && rm -f dist/assets/*.map

# ---------- 2. python dependencies + pinned, verified models
FROM python:3.13.1-slim-bookworm AS py
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv/bmtl/app/backend
# Security audit M-07: every package (including dependencies of dependencies) pinned to the tested version and
# SHA-256 verified; wheels only, so no package build script ever runs. Regenerate: see app/backend/requirements-image.in
COPY app/backend/requirements-image.lock ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --require-hashes --no-deps --only-binary=:all: \
      -r requirements-image.lock --extra-index-url https://download.pytorch.org/whl/cpu \
 && /opt/venv/bin/pip check
COPY app/backend/app ./app
COPY app/backend/vendor ./vendor
ENV HF_HOME=/opt/models/hf TORCH_HOME=/opt/models/torch ALLOW_MODEL_DOWNLOADS=true AUTH_MODE=disabled_local_dev
RUN /opt/venv/bin/python -c "from app.core.models_safe import load_dinov2_vits14, load_clip, load_whisper; \
load_dinov2_vits14(); load_clip('openai/clip-vit-base-patch16'); load_whisper('base','cpu','int8'); print('models verified')"

# ---------- 3. runtime
FROM python:3.13.1-slim-bookworm
RUN groupadd --system bmtl && useradd --system --gid bmtl --home-dir /nonexistent --shell /usr/sbin/nologin bmtl
COPY --from=py /opt/venv /opt/venv
COPY --from=py /opt/models /opt/models
WORKDIR /srv/bmtl
COPY src/realdata ./src/realdata
COPY src/realmodels ./src/realmodels
COPY models/real ./models/real
COPY app/backend/app ./app/backend/app
COPY app/backend/vendor ./app/backend/vendor
COPY app/backend/scripts ./app/backend/scripts
COPY app/mineral/src ./app/mineral/src
COPY app/mineral/models ./app/mineral/models
COPY app/mineral/data ./app/mineral/data
COPY app/data/embeddings ./app/data/embeddings
COPY --from=web /web/dist ./app/dist
RUN chown -R root:root /srv/bmtl /opt && chmod -R a-w /srv/bmtl /opt \
 && mkdir -p /data && chown bmtl:bmtl /data
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/models/hf TORCH_HOME=/opt/models/torch HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    ALLOW_MODEL_DOWNLOADS=false AUTH_MODE=required HOST_BINDING=0.0.0.0 \
    LOCAL_STORAGE_PATH=/data/app USERS_FILE=/data/security/users.json RECORDS_FILE=/data/records/records.db \
    COOKIE_SECURE=true TRUST_PROXY_HEADERS=true
USER bmtl
WORKDIR /srv/bmtl/app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
# Workers: each loads the vision/speech models (~1.5-2 GB RAM). Size WEB_CONCURRENCY to the host's memory.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-4} --proxy-headers --forwarded-allow-ips=${FORWARDED_ALLOW_IPS:-127.0.0.1} --no-server-header --timeout-keep-alive 5 --limit-concurrency ${MAX_CONCURRENCY:-200}"]

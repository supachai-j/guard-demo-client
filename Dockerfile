# -------- Stage 1: Builder --------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv

# Install build dependencies (needed to compile native wheels like
# chromadb-hnswlib for the runtime venv). `git` is intentionally NOT
# installed — requirements.txt has no `git+https://` deps; the old
# upstream-fork clone that needed it was removed.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        python3-dev && \
    python -m venv $VIRTUAL_ENV

ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# -------- Stage 2: Final Image --------
# Using a single-layer approach for runtime dependencies
FROM python:3.12-slim

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    NODE_MAJOR=20 \
    BACKEND_PORT=8000

WORKDIR /home/lakeraai

# Combine all system setup: Node.js, Curl, and Cleanup
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    # Remove package lists to save space
    apt-get purge -y --auto-remove gnupg && \
    rm -rf /var/lib/apt/lists/*

# Bring the venv over from the builder; the app source comes straight from
# the build context (next COPY). The old setup also `COPY --from=builder
# /home/lakeraai` from an upstream `git clone` — that overlay sneaked
# files past .dockerignore (.github, designdocs, RELEASE_NOTES, etc.),
# so we dropped it. Verified the resulting image still serves all 12
# providers.
COPY --from=builder $VIRTUAL_ENV $VIRTUAL_ENV

# Copy local files. .dockerignore excludes node_modules, venv, data,
# tests, docs, etc. — anything not needed at runtime.
COPY . .

EXPOSE 3000
EXPOSE 8000

# Self-describing image health. Compose may override this with its own
# healthcheck block; same shape so the two stay consistent. Generous
# start_period absorbs first-boot npm install + dep verification.
HEALTHCHECK --interval=30s --timeout=5s --retries=5 --start-period=180s \
  CMD curl -fsS "http://localhost:${BACKEND_PORT}/health" || exit 1

CMD ["python", "start_all.py"]

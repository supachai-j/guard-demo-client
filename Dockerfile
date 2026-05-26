# -------- Stage 1: Builder --------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv

# Install build dependencies in one layer and clean up
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        build-essential \
        python3-dev && \
    python -m venv $VIRTUAL_ENV

ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Clone demo client and remove unnecessary files immediately
RUN git clone --depth 1 https://github.com/lakeraai/guard-demo-client /home/lakeraai && \
    rm -rf /home/lakeraai/.git

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

# Copy only necessary artifacts from builder
COPY --from=builder $VIRTUAL_ENV $VIRTUAL_ENV
COPY --from=builder /home/lakeraai /home/lakeraai

# Copy local files (ensure .dockerignore excludes node_modules or venv)
COPY . .

EXPOSE 3000
EXPOSE 8000

# Self-describing image health. Compose may override this with its own
# healthcheck block; same shape so the two stay consistent. Generous
# start_period absorbs first-boot npm install + dep verification.
HEALTHCHECK --interval=30s --timeout=5s --retries=5 --start-period=180s \
  CMD curl -fsS "http://localhost:${BACKEND_PORT}/health" || exit 1

CMD ["python", "start_all.py"]

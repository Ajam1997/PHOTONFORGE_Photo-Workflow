FROM python:3.11-slim-bookworm

LABEL maintainer="PHOTONForge" \
      description="Autonomous Localized Mobile Photography Workflow"

# System dependencies for OpenCV + rsync + SQLite
RUN apt-get update && apt-get install -y --no-install-recommends \
        rsync \
        sqlite3 \
        libglib2.0-0 \
        libgl1 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first for layer caching
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir -e .

# Copy source
COPY src/ ./src/
COPY models/ ./models/
COPY scripts/ ./scripts/
RUN chmod +x scripts/*.sh

# Non-root user for security
RUN useradd -m -u 1000 photon
USER photon

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["photo-workflow"]
CMD ["--help"]

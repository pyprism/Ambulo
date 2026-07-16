FROM python:3.14-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build


RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        python3-dev \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

#  Stage 2: production image
FROM python:3.14-slim AS production

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libexpat1 \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -r ambulo && useradd -r -g ambulo ambulo

WORKDIR /app

# Copy compiled venv from builder
COPY --from=builder /venv /venv

# Copy project
COPY --chown=ambulo:ambulo . .

# Ensure runtime directories are writable by the non-root user.
RUN mkdir -p /app/logs /app/run /app/media /app/staticfiles \
    && chown ambulo:ambulo /app /app/logs /app/run /app/media /app/staticfiles

EXPOSE 8000

USER ambulo

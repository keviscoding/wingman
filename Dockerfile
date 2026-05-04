# Wingman SaaS server — production container.
#
# Mounts TWO surfaces in a single uvicorn process:
#   1. /api/v1/*   — Muzo mobile backend (auth, quick-capture, chats, etc.)
#   2. /editor/*   — Muzo Chat Gen editor tool (viral DM script/renderer)
#
# Both live in the same repo so we deploy once and serve both. The
# editor tool is mounted as a sub-app at /editor by server/saas_app.py.
#
# We build on the official Playwright Python image so Chromium + all
# its system deps (fonts, libx11, etc.) are pre-installed — /editor's
# renderer screenshots HTML via headless Chromium, so we NEED a real
# browser available. The mobile backend doesn't care either way.

FROM mcr.microsoft.com/playwright/python:v1.59.0-jammy

# Build tools needed for Pillow + python-Levenshtein C extensions.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Deps first (so code-only changes reuse the pip layer cache).
COPY requirements-server.txt /app/
RUN pip install --no-cache-dir -r requirements-server.txt

COPY . /app

# Persistent data path — DigitalOcean App Platform mounts the volume
# here. In personal-mode this also resolves correctly.
ENV WINGMAN_SAAS_DB=/app/data/saas/wingman.sqlite3 \
    WINGMAN_HEADLESS=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# --workers 1 so there's exactly one Chromium lifecycle. If we ever
# need mobile-API throughput we should split the editor into its own
# service rather than scale workers here (Chromium doesn't like
# concurrent contexts in the same image).
CMD ["sh", "-c", "uvicorn server.saas_app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]

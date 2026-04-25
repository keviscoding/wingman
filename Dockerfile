# Wingman SaaS server — production container.
#
# Slim Python base + only the server-side requirements. The desktop
# requirements (mss / pyobjc / pynput) are skipped intentionally — they
# don't compile on Linux and we never run the desktop UI here.

FROM python:3.12-slim

# System libs that Pillow + python-Levenshtein need to build wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Layer caching: install deps before copying source so a code-only
# change doesn't bust the pip cache.
COPY requirements-server.txt /app/
RUN pip install --no-cache-dir -r requirements-server.txt

COPY . /app

# Persistent data path — DigitalOcean App Platform mounts the volume
# here. In personal-mode this also resolves correctly.
ENV WINGMAN_SAAS_DB=/app/data/saas/wingman.sqlite3 \
    WINGMAN_HEADLESS=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Honor the platform-supplied PORT; fall back to 8000 for local docker.
# server.saas_app is a slim entry point that only mounts the /api/v1
# routes — no desktop OpenCV/mss/pyobjc imports.
CMD ["sh", "-c", "uvicorn server.saas_app:app --host 0.0.0.0 --port ${PORT:-8000}"]

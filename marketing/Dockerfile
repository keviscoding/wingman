# Muzo editor tool — containerized FastAPI + Playwright + Chromium
#
# We base on the official Playwright Python image so Chromium and all
# its system deps (fonts, X, etc.) are pre-installed and the image
# boots fast. Slim variant keeps us under ~800MB which is fine for DO
# App Platform.
#
# Build (from repo root):   docker build -f marketing/Dockerfile -t muzo-editor .
# Run locally:               docker run -p 8080:8080 -e GEMINI_API_KEYS=... muzo-editor

FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# Install minimal Python deps — the base image already has playwright.
WORKDIR /app

COPY marketing/requirements.txt ./marketing/requirements.txt
RUN pip install --no-cache-dir -r marketing/requirements.txt

# Copy the source we need. Keep the image lean by only copying
# what the marketing service actually uses at runtime.
COPY wingman/config.py ./wingman/config.py
COPY wingman/__init__.py ./wingman/__init__.py
COPY wingman/transcript.py ./wingman/transcript.py
COPY marketing ./marketing
COPY "MARKETING TRAINING CHATS" "./MARKETING TRAINING CHATS"
COPY hook_images_v2 ./hook_images_v2

# Runtime config
ENV HOST=0.0.0.0 \
    PORT=8080 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# Start FastAPI via uvicorn.  --workers=1 keeps Chromium happy and avoids
# concurrent renders fighting for the single browser context. If we
# need throughput we scale horizontally with multiple instances.
CMD ["uvicorn", "marketing.web:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]

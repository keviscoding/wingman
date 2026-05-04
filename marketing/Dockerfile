# Muzo editor tool — containerized FastAPI + Playwright + Chromium
#
# We base on the official Playwright Python image so Chromium and all
# its system deps (fonts, X, etc.) are pre-installed and the image
# boots fast.
#
# Build locally:   docker build -t muzo-editor .
# Run locally:     docker run -p 8080:8080 -e GEMINI_API_KEYS=... muzo-editor

FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

# Python deps first (so Docker cache reuses the layer on code-only changes)
COPY marketing/requirements.txt ./marketing/requirements.txt
RUN pip install --no-cache-dir -r marketing/requirements.txt

# Everything the service needs at runtime
COPY marketing ./marketing
COPY "MARKETING TRAINING CHATS" "./MARKETING TRAINING CHATS"
COPY hook_images_v2 ./hook_images_v2

# Runtime config
ENV HOST=0.0.0.0 \
    PORT=8080 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# Single worker so a single Chromium process owns the render queue.
# Scale horizontally with multiple instances for throughput.
CMD ["uvicorn", "marketing.web:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]

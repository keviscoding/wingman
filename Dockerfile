FROM python:3.12-slim

WORKDIR /app

COPY requirements-server.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY wingman/ wingman/
COPY server/ server/
COPY training/ training/
COPY chats/ chats/
COPY presets.json* ./
COPY .env* ./

ENV WINGMAN_HEADLESS=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "-m", "server"]

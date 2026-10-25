# One container = website + backend, for one-click cloud hosting (Render Blueprint: render.yaml).
# The website (Next.js) listens on $PORT and is password-protected; the API listens on 127.0.0.1 only.

# ---- build the website
FROM node:22-bookworm-slim AS web
WORKDIR /src
ENV NEXT_TELEMETRY_DISABLED=1 NEXT_STANDALONE=1
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build && rm -rf .next/standalone/node_modules/@img .next/standalone/node_modules/sharp

# ---- runtime: Python backend + Node runtime for the prebuilt website
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 \
    ACADEMY_DATA_DIR=/data NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 tesseract-ocr tesseract-ocr-eng tesseract-ocr-ara \
    && rm -rf /var/lib/apt/lists/*
COPY --from=web /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app backend/app
COPY --from=web /src/.next/standalone frontend/
COPY --from=web /src/.next/static frontend/.next/static
COPY start.sh /app/start.sh
RUN node --version && python -c "import pymupdf, fastapi, google.auth"
RUN chmod +x /app/start.sh && mkdir -p /data
EXPOSE 3000
CMD ["sh", "/app/start.sh"]

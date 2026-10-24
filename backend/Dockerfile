FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 ACADEMY_DATA_DIR=/data
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-ara \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-semantic.txt ./
ARG WITH_SEMANTIC=0
RUN pip install --no-cache-dir -r requirements.txt && if [ "$WITH_SEMANTIC" = "1" ]; then pip install --no-cache-dir -r requirements-semantic.txt; fi
COPY app ./app
RUN useradd -m -u 1000 academy && mkdir -p /data && chown academy /data
USER academy
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

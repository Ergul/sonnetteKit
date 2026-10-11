FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home sonnette \
    && mkdir /data && chown sonnette:sonnette /data
COPY server/sonnette ./sonnette
USER sonnette
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"
CMD ["uvicorn", "sonnette.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--ws-max-size", "65536", "--no-access-log"]

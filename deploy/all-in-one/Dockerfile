FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends coturn supervisor \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home sonnette \
    && mkdir /data && chown sonnette:sonnette /data
WORKDIR /app
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server/sonnette ./sonnette
COPY deploy/render_turn.py deploy/turn-entrypoint.py ./
COPY deploy/all-in-one/supervisord.conf /app/supervisord.conf
USER sonnette
# Informational only: Compose publishes host ports. The relay UDP range is
# configured dynamically with TURN_RELAY_MIN_PORT/TURN_RELAY_MAX_PORT.
EXPOSE 8000/tcp 5349/tcp 3478/tcp 3478/udp
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import socket,urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2); socket.create_connection(('127.0.0.1',5349),2).close()"
CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]

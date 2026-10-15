FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends coturn \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home sonnette
WORKDIR /app
COPY deploy/render_turn.py deploy/turn-entrypoint.py ./
USER sonnette
# Informational only: Compose publishes host ports. The relay UDP range is
# configured dynamically with TURN_RELAY_MIN_PORT/TURN_RELAY_MAX_PORT.
EXPOSE 5349/tcp 3478/tcp 3478/udp
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import socket; socket.create_connection(('127.0.0.1',5349),3).close()"
CMD ["python", "/app/turn-entrypoint.py"]

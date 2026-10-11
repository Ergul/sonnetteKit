FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends coturn \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home sonnette
WORKDIR /app
COPY deploy/render_turn.py deploy/turn-entrypoint.py ./
USER sonnette
EXPOSE 5349/tcp 3478/udp 49160-49200/udp
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import socket; socket.create_connection(('127.0.0.1',5349),3).close()"
CMD ["python", "/app/turn-entrypoint.py"]

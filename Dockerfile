# The CLI remains the default target. The HTTP service is opt-in.
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-vector.txt requirements-service.txt /app/
RUN pip install --no-cache-dir -r requirements-vector.txt -r requirements-service.txt
COPY skill/prompt-aid/retrieval /app/skill/prompt-aid/retrieval
RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001

FROM runtime AS service
COPY backend /app/backend
VOLUME ["/data"]
EXPOSE 4318
ENTRYPOINT ["python", "-m", "backend.app"]
CMD ["--root", "/workspace", "--data", "/data", "--host", "0.0.0.0"]

FROM runtime AS retriever
ENTRYPOINT ["python", "/app/skill/prompt-aid/retrieval/cli.py"]

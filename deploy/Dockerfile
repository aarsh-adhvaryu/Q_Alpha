# Q-Alpha dashboard — container image for an always-on host (AWS EC2/Lightsail, etc.).
# Build context is the repo root: `docker build -f deploy/Dockerfile -t qalpha-dash .`
FROM python:3.12-slim

RUN pip install --no-cache-dir uv && apt-get update \
    && apt-get install -y --no-install-recommends git curl bash \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN uv sync --extra dashboard --frozen

EXPOSE 8501
ENTRYPOINT ["bash", "deploy/entrypoint.sh"]

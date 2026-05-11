FROM python:3.13-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    git \
    tar \
    tmux \
    asciinema \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv \
    && pip install --upgrade pip setuptools wheel \
    && pip install \
      camel-ai \
      flask \
      flask-cors \
      openai \
      pydantic \
      python-dotenv \
      pyyaml \
      requests

ARG DARK_CASTLE_ARCHIVE_URL="https://github.com/Tsumugii24/dark-castle/archive/refs/tags/v0.1.0.tar.gz"
ARG DARK_CASTLE_DIR="/sandbox/software/dark-castle"
ENV GBQA_SOFTWARE_DIR="${DARK_CASTLE_DIR}"

RUN mkdir -p "${DARK_CASTLE_DIR}" \
    && curl -fsSL "${DARK_CASTLE_ARCHIVE_URL}" \
      | tar -xz --strip-components=1 -C "${DARK_CASTLE_DIR}" \
    && pip install -r "${DARK_CASTLE_DIR}/backend/requirements.txt"

WORKDIR /sandbox

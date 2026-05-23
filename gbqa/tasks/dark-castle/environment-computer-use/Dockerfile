FROM trycua/cua-xfce:latest

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV VNC_RESOLUTION=1280x720
ENV API_PORT=8030

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gcc \
    git \
    software-properties-common \
    tar \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      python3.12 \
      python3.12-dev \
      python3.12-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3.12 -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install \
      camel-ai \
      cua-sandbox \
      flask \
      flask-cors \
      openai \
      pillow \
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
    && /opt/venv/bin/pip install -r "${DARK_CASTLE_DIR}/backend/requirements.txt"

WORKDIR /sandbox

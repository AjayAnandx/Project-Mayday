FROM mcr.microsoft.com/playwright:v1.61.1-jammy

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    tzdata \
    && echo "deb [trusted=yes] http://ppa.launchpadcontent.net/deadsnakes/ppa/ubuntu jammy main" \
       > /etc/apt/sources.list.d/deadsnakes.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-distutils \
    python3.11-venv \
    && rm -rf /var/lib/apt/lists/* \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 \
    && pip3 install playwright

WORKDIR /workspace

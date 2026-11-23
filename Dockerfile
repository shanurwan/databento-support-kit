FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends netcat-openbsd tcpdump strace curl jq iproute2 dnsutils lsof xxd ca-certificates && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir databento pytest
WORKDIR /w

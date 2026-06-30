FROM python:3.10-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        nmap \
        netcat-openbsd \
        openssl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

CMD ["athena"]

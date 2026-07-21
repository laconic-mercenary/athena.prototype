FROM node:20-alpine AS ui-builder

WORKDIR /ui
COPY src/ui/package*.json ./
RUN npm ci
COPY src/ui/ ./
RUN npm run build


FROM python:3.10-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        nmap \
        netcat-openbsd \
        openssl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
COPY --from=ui-builder /ui/dist /app/src/ui/dist
RUN pip install --no-cache-dir -e ".[dev]"

CMD ["athena"]

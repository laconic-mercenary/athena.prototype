FROM python:3.10-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        netcat-openbsd \
        redis-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Redis auth credential — readable by root only; obtained after privilege escalation
RUN printf 'Meridian2024!' > /root/.redis_password && chmod 600 /root/.redis_password

# SUID on python3.10 — simulates a misconfigured legacy automation account
# python:3.10-slim installs Python to /usr/local/bin, not /usr/bin
RUN chmod u+s /usr/local/bin/python3.10

# Run web service as unprivileged user
USER www-data

EXPOSE 5000
CMD ["python", "app.py"]

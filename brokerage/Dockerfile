FROM python:3.13-slim

WORKDIR /app

# Install dependencies first (layer-cached until requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY api/ ./brokerage/api/

# The .env is bind-mounted at runtime (see docker-compose.yml).
# SQLite database is stored in /data, which is a named volume.
ENV DATA_DIR=/data
RUN mkdir -p /data

EXPOSE 8000

CMD ["uvicorn", "brokerage.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.13-slim

WORKDIR /app

# Install dependencies first (layer-cached until requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY api/ ./marketdata/api/

EXPOSE 8001

CMD ["uvicorn", "marketdata.api.main:app", "--host", "0.0.0.0", "--port", "8001"]

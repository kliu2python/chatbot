FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY data/ ./data/

# Expose port
EXPOSE 8080

# Start the application
CMD ["uvicorn", "app.api.server:app", "--host", "0.0.0.0", "--port", "8080"]
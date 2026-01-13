FROM python:3.9-slim

WORKDIR /app

# Install system dependencies for SSH/network operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirments.txt .
RUN pip install --no-cache-dir -r requirments.txt

# Copy application code
COPY app.py db.py influx_writer.py sideload_client.py \
     teiv_client.py test_orchestrator_rapp.py ue_client.py ./
COPY test_cases/ ./test_cases/

# Create directories for runtime data
RUN mkdir -p /app/logs

# Initialize database schema (optional - can be done at runtime)
COPY migrate_db.sql .

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5000/health')"

# Run as non-root user
RUN useradd -m -u 1000 rapp && chown -R rapp:rapp /app
USER rapp

EXPOSE 5000

CMD ["python", "app.py"]

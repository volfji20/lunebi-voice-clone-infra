# worker/Dockerfile
FROM nvidia/cuda:12.3.1-runtime-ubuntu22.04

# ✅ SET NON-INTERACTIVE ENVIRONMENT FIRST
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    ffmpeg \
    git \
    curl \
    awscli \                         
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN useradd -m -u 1000 worker && \
    chown -R worker:worker /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip3 install --upgrade pip
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy ALL application code
COPY main.py .
COPY src/ ./src/

# Fix permissions
RUN chown -R worker:worker /app

# Create necessary directories
RUN mkdir -p /tmp/segments /tmp/models /app/logs && \
    chown -R worker:worker /tmp/segments /tmp/models /app/logs

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV MODEL_CACHE_DIR=/tmp/models

# Switch to non-root user
USER worker

# Improved health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD python3 -c "\
    import torch; \
    cuda_available = torch.cuda.is_available(); \
    print(f'Health check: GPU available: {cuda_available}'); \
    exit(0 if cuda_available else 1)"

# Run main application
CMD ["python3", "main.py"]
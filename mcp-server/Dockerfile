FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Download translation models at build time (speeds up container startup)
RUN python -c "from transformers import MarianMTModel, MarianTokenizer; \
    print('📥 Downloading Swahili → English model...'); \
    MarianMTModel.from_pretrained('Helsinki-NLP/opus-mt-sw-en'); \
    MarianTokenizer.from_pretrained('Helsinki-NLP/opus-mt-sw-en'); \
    print('📥 Downloading English → Swahili model...'); \
    MarianMTModel.from_pretrained('Helsinki-NLP/opus-mt-en-sw'); \
    MarianTokenizer.from_pretrained('Helsinki-NLP/opus-mt-en-sw'); \
    print('✅ Translation models downloaded!')"

# Copy application code
COPY . .

# Create logs directory
RUN mkdir -p /app/logs

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
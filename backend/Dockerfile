FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including curl for healthcheck
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --timeout=1000 --retries=5 -r requirements.txt

# Download translation models at build time (prevents runtime download delays)
# This is the critical fix - models must be downloaded during build
RUN python -c "from transformers import MarianMTModel, MarianTokenizer; \
    print('📥 Downloading Swahili → English model...'); \
    MarianMTModel.from_pretrained('Helsinki-NLP/opus-mt-sw-en'); \
    MarianTokenizer.from_pretrained('Helsinki-NLP/opus-mt-sw-en'); \
    print('✅ Swahili → English model downloaded!'); \
    print('📥 Downloading English → Swahili model...'); \
    MarianMTModel.from_pretrained('Helsinki-NLP/opus-mt-en-sw'); \
    MarianTokenizer.from_pretrained('Helsinki-NLP/opus-mt-en-sw'); \
    print('✅ English → Swahili model downloaded!'); \
    print('🎉 All translation models ready!')"

# Copy application code
COPY . .

# Create logs directory
RUN mkdir -p /app/logs

# Expose port
EXPOSE 8000

# Health check - increased start period because translation models need time
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]



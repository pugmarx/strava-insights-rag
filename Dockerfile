FROM python:3.11-slim

# Create user with UID 1000 for Hugging Face Spaces
RUN useradd -m -u 1000 user

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PORT=7860 \
    HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# Install system dependencies for psycopg2 and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies as root first for clean caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files and assign ownership to user
COPY --chown=user:user . /app

# Switch to non-root user
USER user

EXPOSE 7860

CMD ["python", "backend/app.py"]

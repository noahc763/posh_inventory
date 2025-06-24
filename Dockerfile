# Dockerfile
FROM python:3.11-slim

# Create app directory
WORKDIR /app

# Install system deps (if needed for Pillow, etc)
RUN apt-get update && \
    apt-get install -y build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . .

# Expose the port Vercel will route to
ENV PORT 8080
EXPOSE 8080

# Run the app with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]

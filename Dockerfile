FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user
RUN groupadd -r crawlmind && useradd -r -g crawlmind crawlmind

# Create data and output directories, change ownership
RUN mkdir -p /app/data /app/output \
    && chown -R crawlmind:crawlmind /app

# Copy application code
COPY . .
RUN chown -R crawlmind:crawlmind /app

# Switch to non-root user
USER crawlmind

# Expose port if MCP is enabled (optional)
EXPOSE 8000

# Set entrypoint
ENTRYPOINT ["python", "-m", "main"]
CMD ["--help"]

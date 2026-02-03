# Dockerfile for VoiceLive Evaluation Agent
# Multi-stage build for smaller final image

# ============================================
# Stage 1: Build stage
# ============================================
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ============================================
# Stage 2: Runtime stage
# ============================================
FROM python:3.11-slim

# Install runtime dependencies for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash agent
WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /home/agent/.local
ENV PATH=/home/agent/.local/bin:$PATH

# Copy application code
COPY --chown=agent:agent . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV EVAL_AGENT_MODE=cloud
ENV EVAL_AGENT_LOG_LEVEL=INFO

# Create directories for runtime data
RUN mkdir -p /app/output /app/logs /app/temp \
    && chown -R agent:agent /app

# Switch to non-root user
USER agent

# Expose port for health checks / API
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import agent; print('healthy')" || exit 1

# Default command - run agent in cloud mode
# Can be overridden to run in interactive mode or with specific arguments
CMD ["python", "agent.py", "--cloud"]

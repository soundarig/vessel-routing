FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.12-slim

# Non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/
COPY main.py .

# Drop to non-root
USER appuser

EXPOSE 8300

# Graceful shutdown: uvicorn handles SIGTERM and drains in-flight requests
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8300", \
     "--workers", "1", "--timeout-graceful-shutdown", "30"]

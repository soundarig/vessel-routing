FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.12-slim

# Install ODBC driver for SQL Server
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg unixodbc-dev \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

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

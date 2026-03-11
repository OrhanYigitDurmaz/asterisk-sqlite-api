FROM python:3.12-alpine

LABEL maintainer="orhan" \
      description="Asterisk 20 PJSIP Realtime provisioning API (SQLite backend)"

# SQLite is included in Alpine base; install build deps for any compiled wheels
RUN apk add --no-cache sqlite-libs

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY schema.sql .
COPY app/ app/

# The shared Docker volume where Asterisk and this API both access pbx.db
VOLUME ["/var/lib/asterisk"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

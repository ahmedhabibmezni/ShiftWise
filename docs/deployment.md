# 🚀 ShiftWise Deployment Guide

> Step-by-step guide for deploying ShiftWise in development and production environments.

---

## 📋 Table of Contents

- [Prerequisites](#prerequisites)
- [Local Development](#-local-development)
- [Production Deployment](#-production-deployment)
- [OpenShift Deployment](#️-openshift-deployment)
- [Environment Configuration](#-environment-configuration)
- [Database Setup](#-database-setup)
- [SSL/TLS Configuration](#-ssltls-configuration)
- [Monitoring](#-monitoring)

---

## Prerequisites

| Component | Minimum Version | Purpose |
|-----------|----------------|---------|
| Python | 3.11+ | Backend runtime |
| PostgreSQL | 16+ | Primary database |
| Node.js | 20+ | Frontend build |
| Redis | 7+ | Task broker (for Celery) |
| OpenShift | 4.18+ | Target cluster (with KubeVirt) |
| Git | 2.40+ | Source control |

---

## 🖥 Local Development

### 1. Clone & Setup Backend

```bash
git clone https://github.com/ahmedhabibmezni/ShiftWise.git
cd ShiftWise/backend

# Virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/macOS

# Dependencies
pip install -r requirements.txt

# Environment configuration
cp .env.example .env
# Edit .env — set DATABASE_PASSWORD and SECRET_KEY at minimum
```

### 2. PostgreSQL Database

```bash
# Option A: Local PostgreSQL
createdb shiftwise_db

# Option B: Docker
docker run -d \
  --name shiftwise-postgres \
  -e POSTGRES_DB=shiftwise_db \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=your_password \
  -p 5432:5432 \
  postgres:16

# Initialize schema
cd backend
python init_db.py
```

### 3. Start Backend

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Verify: `http://localhost:8000/health` → `{"status": "healthy"}`

### 4. Start Frontend

```bash
cd frontend
npm install
npm run dev
```

Verify: `http://localhost:5173`

---

## 🏭 Production Deployment

### Backend (Standalone Server)

```bash
# Install production server
pip install gunicorn

# Run with gunicorn (Linux)
gunicorn app.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --access-logfile - \
  --error-logfile -

# Run with uvicorn (Windows/Linux)
uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4 \
  --log-level info
```

### Frontend (Static Build)

```bash
cd frontend
npm run build
# Output: dist/ directory
# Serve with nginx, Apache, or any static file server
```

### Nginx Configuration (Reverse Proxy)

```nginx
server {
    listen 443 ssl;
    server_name shiftwise.migration.nextstep-it.com;

    ssl_certificate     /etc/ssl/certs/shiftwise.crt;
    ssl_certificate_key /etc/ssl/private/shiftwise.key;

    # Frontend (static files)
    location / {
        root /var/www/shiftwise/dist;
        try_files $uri $uri/ /index.html;
    }

    # Backend API (reverse proxy)
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## ☸️ OpenShift Deployment

### 1. Build Container Image

```dockerfile
# Dockerfile (backend)
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY config/ ./config/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

```bash
# Build and push
podman build -t shiftwise-backend:latest .
podman push shiftwise-backend:latest registry.migration.nextstep-it.com/shiftwise/backend:latest
```

### 2. Deploy to OpenShift

```bash
# Create project
oc new-project shiftwise

# Create secrets
oc create secret generic shiftwise-db \
  --from-literal=DATABASE_HOST=postgres.shiftwise.svc \
  --from-literal=DATABASE_PORT=5432 \
  --from-literal=DATABASE_NAME=shiftwise_db \
  --from-literal=DATABASE_USER=postgres \
  --from-literal=DATABASE_PASSWORD=<password>

oc create secret generic shiftwise-jwt \
  --from-literal=SECRET_KEY=<generated-key>

# Deploy backend
oc new-app shiftwise-backend:latest \
  --name=shiftwise-api \
  --env-from=secret/shiftwise-db \
  --env-from=secret/shiftwise-jwt

# Expose route
oc expose svc/shiftwise-api --hostname=api.shiftwise.apps.migration.nextstep-it.com
```

### 3. Database on OpenShift

```bash
# Deploy PostgreSQL from template
oc new-app postgresql:16 \
  --name=postgres \
  --env=POSTGRESQL_DATABASE=shiftwise_db \
  --env=POSTGRESQL_USER=postgres \
  --env=POSTGRESQL_PASSWORD=<password>
```

### 4. Configure In-Cluster Auth

When running inside OpenShift, the backend auto-detects the ServiceAccount:

```env
KUBERNETES_MODE=incluster
USE_IN_CLUSTER=true
```

---

## ⚙️ Environment Configuration

### Critical Variables (Must Set)

| Variable | Example | Notes |
|----------|---------|-------|
| `DATABASE_PASSWORD` | `S3cur3P@ss!` | Never use defaults |
| `SECRET_KEY` | `openssl rand -hex 64` | Min 32 characters |
| `DEBUG` | `False` | **Must be False in production** |
| `BACKEND_CORS_ORIGINS` | `["https://shiftwise.example.com"]` | Only trusted origins |

### Generate Strong SECRET_KEY

```bash
# Python
python -c "import secrets; print(secrets.token_urlsafe(64))"

# OpenSSL
openssl rand -hex 64
```

---

## 🗄 Database Setup

### Alembic Migrations

```bash
cd backend

# Generate a migration after model changes
alembic revision --autogenerate -m "description of changes"

# Apply all pending migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# View migration history
alembic history
```

### Backup & Restore

```bash
# Backup
pg_dump -h localhost -U postgres shiftwise_db > backup_$(date +%Y%m%d).sql

# Restore
psql -h localhost -U postgres shiftwise_db < backup_20260314.sql
```

---

## 🔒 SSL/TLS Configuration

### For HAProxy (bastion)

SSL termination at the load balancer level using the cluster's wildcard certificate.

### For Direct Backend

```bash
uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8443 \
  --ssl-keyfile=/path/to/key.pem \
  --ssl-certfile=/path/to/cert.pem
```

---

## 📊 Monitoring

### Health Endpoint

Configure monitoring tools to poll:

```
GET /health → 200 OK = healthy
```

### Logging

Set `LOG_LEVEL=INFO` in production. Available levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.

### SonarQube Integration

```bash
# Run SonarQube analysis
sonar-scanner \
  -Dsonar.projectKey=shiftwise \
  -Dsonar.sources=backend/app \
  -Dsonar.tests=backend/tests \
  -Dsonar.python.version=3.11 \
  -Dsonar.host.url=http://sonarqube.example.com
```

# Deployment Config Guide

This directory provides environment templates for backend and web UI deployments.

## Files

- `deploy/env/backend.dev.template`
- `deploy/env/backend.staging.template`
- `deploy/env/backend.prod.template`
- `deploy/env/frontend.dev.template`
- `deploy/env/frontend.staging.template`
- `deploy/env/frontend.prod.template`

## 1) Prepare local runtime env files

Create local files from templates (do not commit secrets):

```bash
mkdir -p deploy/local
cp deploy/env/backend.dev.template deploy/local/backend.dev.env
cp deploy/env/frontend.dev.template deploy/local/frontend.dev.env
cp deploy/env/backend.staging.template deploy/local/backend.staging.env
cp deploy/env/frontend.staging.template deploy/local/frontend.staging.env
```

For staging/prod, copy the matching template and replace all placeholder values.

## 2) Start backend with env file

```bash
set -a
source deploy/local/backend.dev.env
set +a

source .venv/bin/activate
softnix api serve --host 127.0.0.1 --port 8787
```

## 3) Start web UI with env file

```bash
cd web-ui
set -a
source ../deploy/local/frontend.dev.env
set +a
npm run dev
```

## 4) Start both services with Docker Compose

From project root:

```bash
docker compose -f deploy/docker-compose.dev.yml up --build
```

- Backend: `http://127.0.0.1:8787`
- Frontend (Vite dev): `http://127.0.0.1:5173`
- Frontend waits until backend `/health` is healthy before starting

For staging profile:

```bash
docker compose -f deploy/docker-compose.staging.yml up --build -d
```

- Backend: `http://127.0.0.1:8787`
- Frontend (preview): `http://127.0.0.1:4173`
- Frontend waits until backend `/health` is healthy before starting

## 5) Required security checks before staging/prod

- Set a strong `SOFTNIX_API_KEY`
- Restrict `SOFTNIX_CORS_ORIGINS` to only trusted UI domains
- Set explicit backend data paths (`SOFTNIX_WORKSPACE`, `SOFTNIX_RUNS_DIR`, `SOFTNIX_SKILLS_DIR`)
- Keep provider API keys in secret manager or secure CI variables

## 6) Notes

- Backend `.env` loading still works, but deployment should prefer explicit env files per environment.
- Web UI reads `VITE_*` values at startup/build time.

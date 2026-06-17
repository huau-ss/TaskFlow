# TaskFlow — 录音驱动任务协同系统

Monorepo containing Flutter mobile app and FastAPI backend.

## Structure

```
app/
├── backend/          # FastAPI + Celery + LangGraph
├── mobile/           # Flutter (iOS + Android)
├── scripts/          # Connectivity verification
├── docker-compose.yml
└── .env.example
```

## Quick Start (Backend)

```bash
# Copy env and start dependencies (requires Docker)
cp .env.example .env
docker compose up -d postgres redis

# Install Python deps
cd backend
pip install -r requirements.txt

# Run migrations and seed
alembic upgrade head
python scripts/seed.py

# Start API (terminal 1)
uvicorn app.main:app --reload --port 8000

# Start Celery worker (terminal 2)
celery -A app.tasks.celery_app worker --loglevel=info
```

## Verify Connectivity

```bash
python scripts/verify_connectivity.py
```

Checks ASR (`192.168.10.11:8002`), LLM, and backend `/health`.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/auth/login` | JWT login |
| CRUD | `/employees` | Org structure |
| POST | `/meetings/upload` | Upload audio to NAS |
| GET | `/meetings/{id}/transcript` | Diarized transcript |
| POST | `/meetings/{id}/extract-tasks` | LangGraph task extraction |

Default admin: `admin@company.com` / `admin123`

Set `MOCK_ASR=true` in `.env` to test ASR pipeline without the real `:8002` service.

## Mobile App

```bash
cd mobile
# First time: generate platform folders (requires Flutter SDK)
powershell -File ../scripts/setup_mobile.ps1
flutter pub get
flutter run
```

Configure API URL on login screen (`10.0.2.2:8000` for Android emulator).

## Docker (full stack)

```bash
docker compose up --build
```

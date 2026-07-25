# Ambulo Server [![CI](https://github.com/pyprism/Ambulo/actions/workflows/ci.yaml/badge.svg)](https://github.com/pyprism/Ambulo/actions/workflows/ci.yaml) [![codecov](https://codecov.io/gh/pyprism/Ambulo/graph/badge.svg?token=krPfnng0oQ)](https://codecov.io/gh/pyprism/Ambulo)

Self-hostable, privacy-first location tracker and fitness dashboard — the Django REST
API backend. Combines OwnTracks-style location sync with Google Fit-style health
insights. This repo is server only; the Flutter client lives in a separate repo
[Ambulo-Client](https://github.com/pyprism/Ambulo-Client).

The server never decides tracking behavior — it authenticates, stores what the client
sends, and runs background processing (sync, aggregation, geocoding, import/export,
notifications). Collection timing, sync triggers, and conflict UX belong to the client.


## Quickstart for development (no Docker)

```bash
cp .env_example .env   # fill in secret_key, db_*, rabbitmq_url at minimum
./scripts/dockerless_run.sh migrate
./scripts/dockerless_run.sh runserver
```

`dockerless_run.sh` creates a `.venv`, installs `requirements.txt` on first run, and
sources `.env` before every command. It's the required entry point for running any
management command in this project — see `CLAUDE.md`.

```bash
./scripts/dockerless_run.sh makemigrations
./scripts/dockerless_run.sh migrate
./scripts/dockerless_run.sh runserver          # http://localhost:8000
./scripts/dockerless_run.sh celery-worker      # Celery worker
./scripts/dockerless_run.sh celery-beat        # scheduled tasks (rollups, retention)
./scripts/dockerless_run.sh test               # pytest
./scripts/dockerless_run.sh check              # django system check
```

The first account registered (`POST /api/accounts/users/register/`) automatically
becomes admin/superuser. Registration is then normally closed via
`registration_open=false` for production.

## Quickstart (Docker Compose)

```bash
cp .env_example .env
docker compose up -d
```

Brings up `db` (Postgres), `rabbitmq`, `web` (migrates + serves on `server_port`,
default 8002), and `worker`. RabbitMQ needs its vhost created once if you're pointing
at an existing broker instead of the compose one — see `rabbitmq_url` below.


## Testing

```bash
./scripts/dockerless_run.sh test
```

Test files follow the `tests_*.py` naming convention (see `pytest.ini`), one per app,
concentrated on the sync spine's security invariants (idempotency, cross-user
isolation, conflict detection, tombstones) and the friend-block state machine.

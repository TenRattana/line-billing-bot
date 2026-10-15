# LINE Billing Bot — isolated test stack

This checkout is configured as a test-only Docker Compose project. It does not
reuse the production bot's volume or private network. Only the app container
joins the shared `line-router-net` so it can read the existing `central-db`.

**Deploying to a server (pull the CI images, `.env`, folders, nginx, LINE
console): see [docs/DEPLOY.md](docs/DEPLOY.md).**

Before starting, edit `.env` and replace the LINE test channel values and
`PUBLIC_BASE_URL`. Keep `LINE_RICH_MENU_SETUP_ENABLED=false` until the test
channel has been verified.

Start the central database first. The bot joins its external `line-router-net`
network and reads employees from `central-db:5432/central`; it does not call an
employee API. A registration reads the table once (the code step) and checks the
typed name against that result. The app mounts `../db/.env` read-only and
reads its `POSTGRES_PASSWORD`; the password is not copied here.

CI builds the images and pushes them to the registry; the server keeps only
`compose.yaml`, `.env`, `data/` and the DB init files, and pulls. Set
`BOT_IMAGE` and `BACKOFFICE_WEB_IMAGE` in `.env` (e.g.
`ghcr.io/<owner>/line-billing-bot:latest`).

```powershell
docker compose pull
docker compose up -d
docker compose ps
```

For a local build, `docker compose up --build -d` builds the same images.

The bot keeps sessions and per-user locks in memory: run it as one uvicorn
process (the image's default), never with `--workers`.

The `billing-test-bot` container runs `alembic upgrade head` before it starts, so a new image
brings its schema changes with it. If a migration fails, the container stops
instead of serving an old schema; see `docker compose logs billing-test-bot`.

Local endpoints:

- Bot: `http://127.0.0.1:18500`
- Backoffice: `http://127.0.0.1:18510`
- PostgreSQL: `127.0.0.1:15433`

An empty test database starts with no rows; the app's migrations create the
schema on its first start.

To create a test backoffice account after startup:

```powershell
docker compose exec backoffice-api uv run --no-sync python -m backoffice.api.create_admin testadmin
```

Webhook URL: `https://<test-domain>/callback`.

An external Nginx container on `line-router-net` can proxy the bot at
`http://line-billing-test-bot:8500` (the container name).

The app uses the private alias `line-billing-test-db`, avoiding the production
`db` alias on the shared network.

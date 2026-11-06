# LINE Billing Bot

The production Docker Compose project (`line-billing`). It replaces the old
`line_oa` stack; its data lives in database `line_billing` on the shared
`central-db`, and the bot joins `line-router-net` for nginx and `central-db`.

**Deploying to a server (pull the CI images, `.env`, folders, nginx, LINE
console): see [docs/DEPLOY.md](docs/DEPLOY.md).**

`LINE_RICH_MENU_SETUP_ENABLED=true` replaces the channel's rich menus and relinks
every registered user on start; keep it `false` until the bot is the live one.

Start the central database first. The bot joins its external `line-router-net`
network and reads employees from `central-db:5432/central`; it does not call an
employee API. A registration reads the table once (the code step) and checks the
typed name against that result. The app mounts `../db/.env` read-only and
reads its `POSTGRES_PASSWORD`; the password is not copied here.

CI builds the images and pushes them to the registry; the server keeps only
`compose.yaml` and `.env` (plus the data folder `DATA_DIR` points at), and pulls. Set
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

The `billing-bot` container runs `alembic upgrade head` before it starts, so a new image
brings its schema changes with it. If a migration fails, the container stops
instead of serving an old schema; see `docker compose logs billing-bot`.

Local endpoints:

- Bot: `http://127.0.0.1:18500`
- Backoffice: `http://<server-ip>:18510` (LAN, login required)
- PostgreSQL: database `line_billing` on `central-db` (manage it in pgAdmin)

An empty database gets its schema from the app's migrations on first start.

To create a backoffice account after startup:

```powershell
docker compose exec backoffice-api uv run --no-sync python -m backoffice.api.create_admin <username>
```

Webhook URL: `https://<domain>/line-oa/callback`.

An external Nginx container on `line-router-net` can proxy the bot at
`http://line-billing-bot:8500` (the container name).

`DATABASE_URL` uses host `central-db`, never `db`: on the shared network `db`
also resolves to production's `line-platform-db`.

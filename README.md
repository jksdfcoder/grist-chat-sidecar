# Grist chat sidecar

Nginx + unmodified [Grist](https://github.com/gristlabs/grist-core) (`gristlabs/grist`, Apache 2.0) + a FastAPI sidecar. Chat is a same-origin Grist custom widget at `/chat`.

First visit mints a **guest** cookie. There is no OAuth. Anyone who can reach the port can edit the demo sheet.

Do not put API keys in git. Chat, SQL, and Azure upload stay unconfigured until you fill `.env`.

## Run

```bash
cp .env.example .env   # optional; compose boots without it
docker compose up -d --build
```

Open http://127.0.0.1:18080 — you land in Grist as `guest@local`.

Optional `npm run watch` in `chat-ui/` writes `sidecar/static/chat/` (already built in this tree).

## Env

| Variable | What |
|---|---|
| `SIH_SECRET_KEY` | Cookie signing. Compose uses a local placeholder if unset; change it on a public host |
| `SIH_REQUIRE_ROLES` | Compose default `false`: guest is a maintainer (chat / prepare, not Azure commit) |
| `SIH_MANAGERS` | Emails that can commit Azure CSV (`guest@local` if you want guests to commit) |
| `OPENROUTER_API_KEY` | Shared chat. Empty = no OpenRouter models |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` | Optional local OpenAI-compatible (vLLM) |
| `UPSTREAM_*` | Optional read-only Postgres for SQL tools |
| `SIH_SQLITE_PATH` | Saved SQL. Compose uses `/data/sidecar.sqlite` |

Azure stays memory-only until you connect a destination in the upload UI. Do not commit account keys.

## Grist chat widget

Chat is a **custom widget on a Grist page**, same origin.

1. Add New → Empty document. Add columns you care about (e.g. **Email**).
2. Add New → Add Widget to Page → Custom. Data: that table. **Select By**: that table.
3. Custom URL: `http://127.0.0.1:18080/chat`. Grant **full document access**.
4. Ask chat for a lookup. SQL should contain `{{Email}}` (or whatever columns exist).
5. Select rows, **执行 SQL**, then **写入 Grist**.

## Tests

```bash
cd sidecar && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest -q
cd ui && npm test -- --run
cd chat-ui && npm run build
cd e2e && npx playwright test --project=sidecar
```

Playwright sidecar: http://127.0.0.1:18099 (`SIH_E2E=true` in `e2e/playwright.config.ts`).

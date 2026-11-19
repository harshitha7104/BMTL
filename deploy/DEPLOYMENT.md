# Deploying BMTL / ScrapTrust

Status 2026-11-17: code hardened and tested (security suite 30 tests, app 143, pipeline 17; dependency audits clean).
The Docker files below were written and statically checked but **not built here (no Docker on the dev PC)** — build
and run them once on the staging server before go-live.

## 1. Pick a shape

| | Single host (this release) | Several hosts (next step) |
|---|---|---|
| Users | 50,000 accounts, roughly up to ~1,000 people active at the same time on a large server | beyond that, or for high availability |
| State | SQLite (WAL) security DB + files on one volume; Redis for rate limits | PostgreSQL + shared object storage (S3/Azure Blob) + Redis — **code change needed** for DB and file storage |
| Measured | dev PC, 4 workers: 900 mixed requests from 50 concurrent users, 0 errors, ~28 req/s; chat with analysis median 0.9 s, p95 4.3 s | — |

Rule of thumb: 1 worker ≈ 1.5–2 GB RAM (vision + speech models). A 16-core / 64 GB server with 16–24 workers is a
reasonable start; confirm with the load test in `docs/TESTING_SESSION.md` before go-live.

## 2. Staging, then production (Docker)

```
cp deploy/.env.production.example deploy/.env.production      # fill in domain + SECRET_KEY; never commit this file
docker compose -f deploy/docker-compose.yml --env-file deploy/.env.production up -d --build
docker compose -f deploy/docker-compose.yml exec app python scripts/manage_users.py add <admin> --role admin
docker compose -f deploy/docker-compose.yml exec app python scripts/manage_users.py import staff.csv /data/onetime.csv
```
What the stack enforces: HTTPS only (Caddy, automatic certificates, HSTS), the app is not reachable except through
the proxy, containers run read-only as a non-root user with all Linux capabilities dropped, models are baked in and
checksum-verified at build time, nothing is downloaded at run time, Redis is internal-only.

## 3. Without Docker (Windows server)

1. Python 3.13 + Node 22; `app\backend\venv` with `requirements.txt`, `requirements-copilot.txt`, `requirements-phase-b.txt` (+ `requirements-dev.txt` for tests).
   The Docker image instead installs `app/backend/requirements-image.lock`: every package pinned to the tested version with SHA-256
   hashes (`pip install --require-hashes --only-binary=:all:`). After changing any `requirements*.txt`, refresh `requirements-tested.txt`
   (`pip freeze` of the venv the tests passed on), regenerate the lock with the `uv pip compile` command in `requirements-image.in`,
   then run `pip-audit --disable-pip --no-deps -r requirements-image.lock`.
2. `npm ci && npm run build` in `app\`.
3. `app\backend\.env`: same keys as `.env.production.example`.
4. Run `uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers N --proxy-headers` from `app\backend` as a service
   (NSSM / Windows Service) under a dedicated low-privilege account.
5. Put IIS (ARR) or nginx in front with a real TLS certificate; only the proxy listens on the network.
6. Schedule `scripts\housekeeping.py` daily (Task Scheduler).

## 4. Before go-live (owners)

| # | Item | Owner |
|---|---|---|
| 1 | Domain + TLS certificate; `TRUSTED_HOSTS`, `CORS_ORIGINS` set | IT |
| 2 | Company single sign-on (OIDC/SAML) — recommended for 50k staff instead of local passwords; swap point is `app/core/security.py:current_user` | IT + dev |
| 3 | Decide LLM use: offline mode keeps all data in-house; an API key sends user text/photos to that provider (legal approval) | Legal / IT |
| 4 | Backups of the `bmtl-data` volume (security.db + conversations + uploads), tested restore | IT |
| 5 | Malware scanning of uploads (e.g. ClamAV sidecar) if files are shared between staff | IT |
| 6 | Central log collection; alert on `login_locked_out`, `link_refused`, 5xx spikes (audit table `audit_log` in security.db) | IT |
| 7 | Monthly `pip-audit` + `npm audit` and image rebuilds | dev |
| 8 | Independent penetration test on staging | Security |
| 9 | Testing session sign-off (`docs/TESTING_SESSION.md`) | Business |
| 10 | Delete `app/backend/data/security/TEST_ACCOUNTS.csv` and disable the test_* accounts | Admin |

## 5. Operations

```
python scripts/manage_users.py list | add | import | role | disable | enable | reset | signout
python scripts/housekeeping.py [--dry-run]          # retention, prune, reindex
```
Rollback: keep the previous image tag (`bmtl:<previous>`); `docker compose up -d` with it. The data volume is
forward-compatible (tables are created if missing, never dropped).

## Hugging Face Space (NOT free: since 2026 Docker Spaces need a PRO plan; HF answered 402 on 2026-11-18)
`deploy/hf_space/`: `publish.py` packs code + fitted models + embeddings into a bundle, uploads it to a PRIVATE dataset
repo `<user>/scraptrust-bundle`, and creates the PUBLIC Docker Space `<user>/scraptrust` holding only the generated
Dockerfile (bundle SHA-256 pinned) and README. Settings: `AUTH_MODE=public_demo`, `PUBLIC_RECORDS=true`, offline Copilot,
`TRUSTED_HOSTS` from HF's `SPACE_HOST`, secrets `SECRET_KEY` (random) and `HF_TOKEN` (build only, removed from the app's
environment). Free CPU basic: storage is temporary (chats/Records wiped on restart), sleeps after 48 h idle.
```
app/backend/venv/Scripts/hf.exe auth login                       # once; token typed into a hidden prompt
app/backend/venv/Scripts/python.exe deploy/hf_space/publish.py   # --dry-run builds locally only
```
Testers use the direct link `https://<user>-scraptrust.hf.space` (the huggingface.co page can't frame the app).

## Free open testing from this laptop (used for the 2026-11 round)
`app/OpenTesting.bat` (-> `app/run_open_testing.ps1`): open-testing mode (`public_demo`, `PUBLIC_RECORDS=true`, offline
Copilot) on 127.0.0.1:8040 plus a free Cloudflare quick link (`tools/cloudflared.exe`, Cloudflare-signed, no account).
Own data folder `app/backend/data/open_testing/` (own SECRET_KEY, chats, Records), so testers never see local-dev data.
The link works only while the laptop is on, awake (the script blocks sleep while open; closing the lid may still sleep)
and online, and it CHANGES on every start: send the new one. Link saved to the Desktop as "ScrapTrust test link.txt".

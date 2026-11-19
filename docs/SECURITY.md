# BMTL / ScrapTrust security

Written 2026-11-16 for a rollout to tens of thousands of users. Each line names an attack, what now
stops it in the code, and the test that proves it (`app/backend/tests/test_security.py`, 23 tests).

## What an attacker would try, and what stops it

| Attack | Control | Where | Tested |
|---|---|---|---|
| Use the app without an account, read everyone's chats and uploads | Login required for every `/api/v1` route; no self-registration (admins create accounts) | `core/security.py`, `main.py` | yes |
| Read / delete / reply into another user's conversation by guessing its id | Every session has an owner; someone else's id answers **404** (not 403), so ids cannot be probed | `copilot/service.py` | yes |
| Open another user's photo assessment | Ownership index on assessments; same 404 behaviour | `core/ownership.py` | – |
| Forge or tamper with the sign-in cookie | HMAC-SHA256-signed token (SECRET_KEY), expiry, constant-time compare | `issue_token` / `read_token` | yes |
| Steal the cookie with injected script | Cookie is HttpOnly + SameSite=Strict (+ Secure behind HTTPS); JavaScript never sees it | `routes/auth.py` | yes |
| Keep using a stolen session after the user is disabled / changes password | Per-user `token_version`; disabling, role change, reset or "signout" revokes all sessions at once | `UserStore.update` | yes |
| Guess passwords | scrypt hashes; lockout after 5 failures per account+IP (15 min) plus a per-IP cap against spraying; identical error for unknown user and wrong password (no enumeration); min 12 chars | `routes/auth.py` | yes |
| Cross-site request forgery | SameSite=Strict cookie + Origin/Referer check on every POST/DELETE | `core/middleware.py` | yes |
| Upload an HTML/SVG file that runs script for whoever opens it (stored XSS) | Only images/audio/video are served inline, with a server-chosen type; everything else is a forced download as `application/octet-stream` under `CSP: sandbox` | `routes/copilot.py` | yes |
| Script injection through chat answers | Markdown is rendered as React elements, never `innerHTML`; links limited to http(s); strict CSP on every page | `Markdown.tsx`, middleware | – |
| Clickjacking, MIME sniffing | `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer` | middleware | yes |
| Exhaust memory/disk with huge uploads | Request cap checked from Content-Length before reading; uploads read in chunks and stopped at the limit; max files per message | middleware, `read_limited` | yes |
| Zip bomb / path traversal / symlinks in a "folder" | Member count, total size and per-member ratio caps, size re-checked while reading, names reduced to a sanitised basename, nested archives/symlinks/encrypted members skipped | `engines/intake.py` | yes |
| Make the server fetch internal URLs (SSRF: cloud metadata, localhost admin, intranet) | Only http(s) on 80/443, no credentials in URL, every resolved IP must be public, connection pinned to the vetted IP (defeats DNS rebinding), redirects re-vetted, size and time caps, optional allow/deny domain lists | `engines/intake.py` | yes |
| XML bombs inside .xlsx | `defusedxml` installed (openpyxl uses it automatically) | requirements | – |
| Decompression-bomb images | Pixel cap before decoding, downscale, per-photo OCR time budget | `ocr_screen.py` | – |
| Run up LLM / CPU costs | Per-user rate limits on chat, transcription, link fetches and assessments | `rate_limited` | – |
| Poison retraining data with fake feedback | Feedback export needs reviewer role; reviewer name is the signed-in user, never client-supplied | `routes/feedback.py`, `routes/copilot.py` | yes |
| Prompt injection hidden in a PDF, web page or photo | System prompt treats all attachment/link/OCR text as data; tools are read-only (no tool can send, delete or reach other users) | `copilot/prompts.py` | – |
| Deploy with a weak/default secret or with login switched off on a network | Server refuses to start: SECRET_KEY must be random and >= 32 chars; `AUTH_MODE=disabled_local_dev` only allowed when bound to localhost | `startup_security_check` | yes |
| API reconnaissance | `/docs`, `/redoc`, `/openapi.json` off unless `EXPOSE_API_DOCS=true` | `main.py` | yes |
| Leak internals in errors | Generic error bodies; stack traces only in server logs | `core/exceptions.py` | – |
| Wrong numbers presented as facts | Every value labelled OBSERVED / INFERRED / UNKNOWN; OCR'd photo values marked "read from photo"; impossible totals (> 100 %) are refused, not assessed | `black_mass.py`, `extract.py` | yes |

## Added 2026-11-17 (deployment hardening for 50k users)

| Attack / risk | Control | Tested |
|---|---|---|
| Known vulnerabilities in libraries | Upgraded starlette/fastapi, python-multipart, Pillow (72 advisories), python-dotenv, pytest; removed unused python-jose/ecdsa and 8 unused web packages; `pip-audit` and `npm audit` now report 0 | audit |
| Remote code from GitHub at runtime (DINOv2 `torch.hub` with `trust_repo=True`) | Model code vendored (Apache-2.0); weights SHA-256-verified and loaded with `weights_only=True`; CLIP pinned to a revision; nothing downloads unless `ALLOW_MODEL_DOWNLOADS=true` (build time only) | load check |
| Stolen cookie still valid after sign-out | Sign-out revokes that session server-side | yes |
| Several worker processes: lost updates, per-worker (N x) rate limits | Users, rate limits, ownership, session index and audit log in one SQLite DB (WAL, transactions); Redis for several hosts | yes (4 processes) |
| Disk exhaustion by one user | Per-user storage quota (default 500 MB) | yes |
| A few heavy uploads starving everyone | Fixed heavy-job slots per worker; "busy, try again" instead of slowdown | yes |
| Host-header poisoning | `TRUSTED_HOSTS` allow-list | yes |
| No trail of security events | Append-only `audit_log` (sign-ins, lockouts, password changes, admin actions, refused links) | yes |
| Data kept forever | `SESSION_RETENTION_DAYS` + daily `scripts/housekeeping.py` | – |
| Decompression-bomb images anywhere | Global Pillow pixel limit at startup | – |
| Load | 900 requests from 50 concurrent users on 4 workers, 0 errors, user isolation verified | load test |

## Still required before 50k users (not done in code here)

1. **HTTPS reverse proxy** (nginx/IIS/cloud LB) in front of uvicorn; set `COOKIE_SECURE=true` (adds Secure + HSTS) and `TRUST_PROXY_HEADERS=true` only behind that proxy.
2. **Company single sign-on (OIDC/SAML)** instead of local passwords for this many people. The `current_user` dependency is the single place to swap.
3. **Several servers**: users/rate limits/index are now multi-process safe on ONE host (SQLite WAL + optional Redis). Running several hosts needs PostgreSQL and shared object storage for conversations/uploads (code change).
4. **LLM data residency**: with an API key set, user text and photos are sent to that provider. Agree this with legal/IT, or run the Copilot in offline mode (all analysis is local) or with a self-hosted model. **Decision 2026-11-17 (manager): do not use Anthropic.** The app is pinned to `COPILOT_PROVIDER=offline` in `app/backend/.env` and no AI keys are set, so no user data leaves the server. If any AI provider is configured later and fails (outage, rate limit, budget), the Copilot answers with the offline engine and logs `ai_provider_fallback` in the audit log.
5. **Malware scanning** of uploads (e.g. ClamAV) before files are stored, if files are ever downloaded by other staff.
6. **Backups and retention** for `app/backend/data/` (conversations, uploads, users) and a deletion policy.
7. **Central logging/alerting** on `app.security` log lines (failed logins, lockouts, refused links) and dependency patching (`pip-audit`, `npm audit`) on a schedule.
8. An independent **penetration test** before go-live.

## Operating it

```
backend\venv\Scripts\python.exe backend\scripts\manage_users.py add <name> [--role reviewer|admin]
backend\venv\Scripts\python.exe backend\scripts\manage_users.py import staff.csv passwords_out.csv
backend\venv\Scripts\python.exe backend\scripts\manage_users.py disable <name>      # also signs them out everywhere
```
The launcher (`app\ScrapTrust.bat`) generates SECRET_KEY on first run and asks for the first admin account.
Never commit `app/backend/.env` or `app/backend/data/security/`.

## Records database and self-learning (added 2026-11-17)
- `app/backend/data/records/records.db` stores every input and action (messages, uploads with extracted text, tool results,
  replies, sign-ins, library actions, admin views). It is personal and commercial data: back it up, restrict file access,
  and tell users in the terms of use that inputs are recorded and may be used to improve the models. Set
  `RECORDS_RETENTION_DAYS` if a retention limit is required (default 0 = keep everything).
- Users see only their own library items (other users' items answer 404). The activity log, readings and learning status
  are admin-only (403 for everyone else); admin event views, exports and lab labelling are themselves logged.
- Self-learning trains only on readings an admin has labelled with a real lab (ICP-OES) result; a candidate model goes live
  only if it beats the current one on the original held-out samples, and the previous model is backed up first.

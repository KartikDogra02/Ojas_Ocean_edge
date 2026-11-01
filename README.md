# Ojas Ocean Edge API

FastAPI + MongoDB backend for managing users and service engineers.

## Quick start

```bash
cp .env.example .env   # then edit the values - at minimum MONGO_ROOT_PASSWORD, JWT_SECRET, INITIAL_ADMIN_PASSWORD
docker compose up -d --build
```

- API: http://localhost:8000 (interactive docs at `/docs`)
- MongoDB: `localhost:27017` (bound to localhost only, auth required)

On startup the API creates an admin user from the `INITIAL_ADMIN_*` settings if no admin exists yet.
That admin must change their password on first login.

## Auth

1. `POST /auth/login` with form fields `username` (or email) and `password` → returns a bearer token.
2. Send `Authorization: Bearer <token>` on every other request.
3. Passwords are temporary by default: any password set by an admin (new users, service engineers, resets) must be
   changed with `POST /auth/change-password` before anything else works (other calls return 403 "Password change required").

## File storage (receipts and signatures)

`STORAGE_BACKEND` chooses where uploaded files live:

- `gridfs` (default): inside MongoDB — nothing else to set up.
- `r2`: a Cloudflare R2 bucket; MongoDB only stores each file's key.

To use R2:

1. In the Cloudflare dashboard, create a **private** R2 bucket.
2. Create an R2 API token with **Object Read & Write**, applied to that bucket only.
3. In `.env` set `STORAGE_BACKEND=r2`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` and `R2_BUCKET`,
   then restart the API. It checks the bucket on startup and refuses to start if it can't reach it.

Files are always uploaded and checked through the API. They can be downloaded through the API, or with R2 via a
short-lived direct link (`.../receipt/link`, `.../signature/link`, valid for `FILE_LINK_EXPIRY_SECONDS`).

### Moving existing files

`app/migrate_files.py` copies receipts and signatures into the current backend: legacy GridFS files from before the
storage layer, and GridFS files when switching to R2. Each copy is read back and checked before the database is
updated; re-running it skips files already in place. Run it with the target settings in `.env`:

```bash
docker compose exec api python -m app.migrate_files --dry-run        # show what would be copied
docker compose exec api python -m app.migrate_files                  # copy (GridFS copies are kept)
docker compose exec api python -m app.migrate_files --delete-source  # remove GridFS copies once you're happy
```

It exits with code 1 and lists any file it couldn't copy (for example one already missing from GridFS).

For local testing without R2: `docker compose --profile s3 up -d s3` starts an S3-compatible SeaweedFS server;
create a bucket in it and set `R2_ENDPOINT=http://s3:8333`.

## Security settings

- **Login lockout:** after `LOGIN_MAX_ATTEMPTS` (5) failed logins for the same username from the same address, further
  attempts get `429` with a `Retry-After` header for `LOGIN_LOCKOUT_MINUTES` (15).
- **API docs:** `/docs`, `/redoc` and `/openapi.json` can be turned off with `API_DOCS_ENABLED=false`.
- **Startup checks:** the API refuses to start if `JWT_SECRET` is shorter than 32 characters or `APP_TIMEZONE` isn't a
  real time zone.
- **Paging:** list endpoints take `skip` and `limit` (1–500) and return the total in an `X-Total-Count` header.

## Running in production (Docker image)

- The image installs exactly the versions in `uv.lock` (no dev tools) and runs as an unprivileged user.
- `WEB_CONCURRENCY` sets the number of worker processes (default 2; roughly one per CPU core).
- **Behind a reverse proxy / load balancer:** set `FORWARDED_ALLOW_IPS` to the proxy's address (or `*` if only the
  proxy can reach the container) so client IPs come from `X-Forwarded-For`. The login lockout counts failures per
  client IP, so without this every user appears to come from the proxy. Don't use `*` if the API is reachable directly:
  clients could then fake their IP.
- The container has a healthcheck on `/health`; `docker compose ps` shows `healthy` once it's serving.

## Audit log and request logs

- **Audit log:** every change (users, roles, permissions, planner, work plans/orders, FSRs, expense claims, certificates,
  reference standards, signatures, password changes) records who did it, when, and the fields changed (before → after).
  Passwords and hashes are never stored. Admin and owner can read it at `GET /audit-log?entity_type=&entity=&actor=&action=&since=&until=`
  (`entity` takes an id or a number such as `WO-2026-001`). Entries are kept for `AUDIT_RETENTION_DAYS` (730).
- **Request logs:** one line per request (method, path, status, duration, user). Each response has an `X-Request-ID`
  header (a client-supplied one is reused), and audit entries store the same id. `LOG_LEVEL` sets the level (INFO).

## MongoDB replica set and transactions

Steps that change several records at once (converting a work plan, submitting an FSR, deleting a work order or a
role) run in a MongoDB transaction, so a failure part way through saves nothing. Transactions need a replica set:

- **Docker Compose** runs Mongo as a one-node replica set (`rs0`). On first start it creates the internal keyfile and
  initialises the set; existing data volumes are kept. The healthcheck waits until the node is primary.
- **API outside Docker:** keep `directConnection=true` in `MONGO_URI` (see `.env.example`), because the set
  advertises the host name `mongo`, which only resolves inside Docker.
- **Production:** the database must be a replica set too (MongoDB Atlas always is). A standalone `mongod` fails with
  "Transaction numbers are only allowed on a replica set member or mongos".

Uploaded files (FSR client signatures) can't be part of a transaction; they're saved first and deleted if the
transaction fails. Document numbers (e.g. `WO-…`, `FSR-…`) are allocated outside it, so a failed attempt can
skip a number.

## CORS

Browser frontends must be listed in `CORS_ORIGINS` in `.env` (comma-separated exact origins, e.g.
`https://app.ojasoceanedge.com,http://localhost:5173`). Restart the API after changing it.

## Roles

The five built-in system roles are created on startup and can't be deleted or renamed:

| Role | Can |
|---|---|
| `admin` | Everything, including users, roles and the menu permission matrix |
| `hr_team` | View service engineers and roles |
| `technical_team` | Basic access |
| `service_engineer` | Basic access, view own profile (`GET /users/me`) |
| `owner` | Final approval of expense claims |

Admins can add custom roles (e.g. `sonar_specialist`) via `/roles` and assign them to users. Custom roles control
which frontend menus a user sees (via the permission matrix); API access itself is governed by the system roles.

Expense claims go `pending` → `technical_approved` → `owner_approved` → `reimbursed` (or `rejected` by the
technical team or owner at their stage). Nobody can act on their own claim, or act on the same claim twice.

## Main endpoints

| Endpoint | Access |
|---|---|
| `POST /auth/login` | Public |
| `POST /auth/change-password`, `POST /auth/logout` | Logged in |
| `GET /users/me` | Logged in |
| `/users` (CRUD) | Admin — the `service_engineer` role is only assigned via `/service-engineers` |
| `POST /service-engineers` | Admin — auto-allocates an `ENG-<year>-<seq>` ID and optional temporary password |
| `GET /service-engineers?territory=&skill=&active=` | Admin, HR |
| `PUT`/`DELETE /service-engineers/{engineer_id}/signature` | Admin — signature PNG only, up to `SIGNATURE_MAX_KB` |
| `GET /service-engineers/{engineer_id}/signature`, `/signature/link` | Admin, HR — the PNG, or a short-lived R2 link |
| `PUT`/`GET`/`DELETE /users/me/signature`, `GET /users/me/signature/link` | Service engineers — manage your own signature |
| `GET /options` | Logged in — active roles and territories (value + label) for dropdowns |
| `GET /roles`, `GET /roles/{id_or_code}` | Admin, HR — with `user_count` |
| `POST`/`PATCH`/`DELETE /roles...` | Admin — custom roles; system roles can't be renamed, deactivated or deleted |
| `GET /permissions` (alias `/roles/permissions/matrix`) | Logged in — roles plus which roles see each menu item |
| `PUT /permissions` | Admin — bulk save per menu item (`{"permissions": [{menu_id, permissions: {role: bool}}]}`) |
| `PUT /roles/permissions/matrix` | Admin — bulk save as `{"matrix": [{menu_id, role_code, is_allowed}]}` |
| `GET /permissions/me` (alias `/users/me/permissions`) | Logged in — menus the current user may see (sidebar) |
| `GET /reference-standards?due_before=&storage_location_id=` | Logged in — sorted by due date |
| `POST /reference-standards` | Technical team, service engineers |
| `PATCH`/`DELETE /reference-standards/{id}` | Admin, technical team — can't delete a standard used by a certificate |
| `GET /certificates?customer=&serial_number=&instrument_type=&result=&reference_standard_id=` | Logged in |
| `GET /certificates/{id_or_number}` | Logged in — e.g. `CAL-2026-10-0001` (year, month, then up to 9999 a month) |
| `POST /certificates` | Technical team, service engineers — auto-numbered; standards must be in calibration; `test_points` take nominal/observed values (deviation and pass/fail are calculated); optional `work_order` link |
| `DELETE /certificates/{id}` | Admin |
| `GET /work-plans?priority=&status=&engineer_id=&customer=` | Admin, HR, technical team, owner see all; service engineers see plans they're assigned to |
| `GET /work-plans/{id_or_number}` | As above — e.g. `WP-2026-001` |
| `POST`/`PATCH`/`DELETE /work-plans...` | Admin, technical team — assign engineers by ID (`ENG-2026-001`); none = draft |
| `POST /work-plans/{id}/convert` | Technical team only — turns the plan into a dispatched work order (needs `service_type`); the plan is then locked |
| `POST /work-orders` | Technical team only — create and dispatch directly; at least one engineer, `lead_engineer_id` defaults to the first |
| `GET /work-orders?priority=&service_type=&engineer_id=&customer=&work_plan=` | Admin, HR, technical team, owner see all; service engineers see work orders they're on |
| `PATCH`/`DELETE /work-orders/{id_or_number}` | Admin, technical team — deleting a converted work order unlocks its plan |
| `POST /work-orders/{id_or_number}/start` | Crew or technical team — dispatched → in progress |
| `POST /fsr` | Engineers on the work order's crew — Digital Field Service Report; completes the work order (one per work order) |
| `GET /fsr?work_order=&customer=`, `GET /fsr/{id_or_number}` | Admin, HR, technical team, owner see all; engineers see FSRs for work orders they were on |
| `GET /fsr/{id}/signature`, `/signature/link` | The client's drawn signature (PNG) |
| `POST /check-ins` | Service engineers — type where they are (hotel, vessel, airport, workshop, customer site, other) |
| `GET /check-ins?engineer_id=&place_type=`, `GET /check-ins/latest` | History, and each engineer's latest check-in (where they are now) |
| `GET /workflow?search=&stage=&priority=` | Each job traced Work Plan → Work Order → Crew → FSR → ISO certificate, with expenses and completion % |
| `GET /planner/daily` | Today + 13 days per engineer: status, note, work order, availability, daily totals |
| `PUT /planner/daily` | HR, technical team — bulk set/clear days (today to today+13 only; past days auto-delete) |
| `GET /planner/weekly?start=` | 7 days with each engineer's work orders (defaults to this week's Monday) |
| `GET /planner/monthly?year=`, `PUT /planner/monthly` | Whole year: month off / on call per engineer (editing: HR, technical team; current year onwards) |
| `GET /planner/availability` | Which of the next 14 days each engineer is free |
| `PATCH /planner/engineers/{engineer_id}` | HR, technical team — current country and planner comment |

Planner: HR and the technical team see every engineer and make changes; admin and owner can view everyone
(read-only); service engineers see only their own row and can't change it.
`APP_TIMEZONE` (default UTC; `PLANNER_TIMEZONE` also accepted) decides what "today" is, and the month in
document numbers such as `CAL-2026-10-0001`.
| `POST /expense-claims` | Logged in — submit your own claim; `amount` or (Travel & Fuel) `distance_km` at `MILEAGE_RATE_PER_KM` |
| `GET /expense-claims?status=&category=&work_plan=&claimant_id=&awaiting_my_action=` | Admin, HR, technical team and owner see all claims; everyone else sees their own |
| `POST /expense-claims/{id}/receipt` | Claimant, while pending — PDF/JPEG/PNG/WebP up to `RECEIPT_MAX_MB` |
| `GET /expense-claims/{id}/receipt`, `/receipt/link` | Claimant and those who can see the claim — file, or a short-lived R2 link |
| `DELETE /expense-claims/{id}` | Claimant — withdraw a pending claim |
| `POST /expense-claims/{id}/approve`, `/reject` | Technical team (pending), then owner (technical-approved); reject needs a `reason` |
| `POST /expense-claims/{id}/reimburse` | HR, once the owner has approved — optional `payment_reference` |

## Local development (API outside Docker)

```bash
docker compose up -d mongo
uv run fastapi dev app/main.py
```

## Running tests

The tests run the real API against a throwaway database (`ojas_test_<random>`) in the Docker MongoDB, using the
connection settings in `.env`. Your normal data isn't touched.

```bash
docker compose up -d mongo
uv run pytest
```

Before pushing, run the same checks as CI (`.github/workflows/ci.yml`, which runs on every PR and on `main`):

```bash
uv run ruff check && uv run ruff format --check && uv run pyright && uv run pytest
```

## Admin CLI

Create an extra admin, e.g. to recover access if every admin is locked out:

```bash
docker compose exec api python -m app.cli create-admin --email you@example.com --username admin2
```

The password is temporary unless you pass `--permanent-password`.

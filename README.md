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

## CORS

Browser frontends must be listed in `CORS_ORIGINS` in `.env` (comma-separated exact origins, e.g.
`https://app.ojasoceanedge.com,http://localhost:5173`). Restart the API after changing it.

## Roles

| Role | Can |
|---|---|
| `admin` | Everything, including creating/editing/deleting users and service engineers |
| `hr_team` | View service engineers |
| `technical_team` | Basic access |
| `service_engineer` | Basic access, view own profile (`GET /users/me`) |

## Main endpoints

| Endpoint | Access |
|---|---|
| `POST /auth/login` | Public |
| `POST /auth/change-password`, `POST /auth/logout` | Logged in |
| `GET /users/me` | Logged in |
| `/users` (CRUD) | Admin — the `service_engineer` role is only assigned via `/service-engineers` |
| `POST /service-engineers` | Admin — auto-allocates an `ENG-<year>-<seq>` ID and optional temporary password |
| `GET /service-engineers?territory=&skill=&active=` | Admin, HR |
| `GET /options` | Logged in — role and territory values + labels for dropdowns |

## Local development (API outside Docker)

```bash
docker compose up -d mongo
uv run fastapi dev app/main.py
```

## Admin CLI

Create an extra admin, e.g. to recover access if every admin is locked out:

```bash
docker compose exec api python -m app.cli create-admin --email you@example.com --username admin2
```

The password is temporary unless you pass `--permanent-password`.

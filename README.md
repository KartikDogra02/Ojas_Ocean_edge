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

The four built-in system roles are created on startup and can't be deleted or renamed:

| Role | Can |
|---|---|
| `admin` | Everything, including users, roles and the menu permission matrix |
| `hr_team` | View service engineers and roles |
| `technical_team` | Basic access |
| `service_engineer` | Basic access, view own profile (`GET /users/me`) |

Admins can add custom roles (e.g. `sonar_specialist`) via `/roles` and assign them to users. Custom roles control
which frontend menus a user sees (via the permission matrix); API access itself is governed by the system roles.

## Main endpoints

| Endpoint | Access |
|---|---|
| `POST /auth/login` | Public |
| `POST /auth/change-password`, `POST /auth/logout` | Logged in |
| `GET /users/me` | Logged in |
| `/users` (CRUD) | Admin — the `service_engineer` role is only assigned via `/service-engineers` |
| `POST /service-engineers` | Admin — auto-allocates an `ENG-<year>-<seq>` ID and optional temporary password |
| `GET /service-engineers?territory=&skill=&active=` | Admin, HR |
| `GET /options` | Logged in — active roles and territories (value + label) for dropdowns |
| `GET /roles`, `GET /roles/{id_or_code}` | Admin, HR — with `user_count` |
| `POST`/`PATCH`/`DELETE /roles...` | Admin — custom roles; system roles can't be renamed, deactivated or deleted |
| `GET /roles/permissions/matrix` | Logged in — which roles see each menu item |
| `PUT /roles/permissions/matrix` | Admin — bulk update; all entries are validated before any are saved |
| `GET /reference-standards?due_before=&storage_location_id=` | Logged in — sorted by due date |
| `POST /reference-standards` | Technical team, service engineers |
| `PATCH`/`DELETE /reference-standards/{id}` | Admin, technical team — can't delete a standard used by a certificate |

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

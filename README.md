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
| `PUT`/`DELETE /service-engineers/{engineer_id}/signature` | Admin — signature PNG only, up to `SIGNATURE_MAX_KB` (stored in GridFS) |
| `GET /service-engineers/{engineer_id}/signature` | Admin, HR — returns the PNG |
| `PUT`/`GET`/`DELETE /users/me/signature` | Service engineers — manage your own signature |
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
| `GET /certificates/{id_or_number}` | Logged in — e.g. `CAL-2026-001` |
| `POST /certificates` | Technical team, service engineers — auto-numbered; standards must be in calibration; `test_points` take nominal/observed values (deviation and pass/fail are calculated) |
| `DELETE /certificates/{id}` | Admin |
| `GET /work-plans?priority=&status=&engineer_id=&customer=` | Admin, HR, technical team see all; service engineers see plans they're assigned to |
| `GET /work-plans/{id_or_number}` | As above — e.g. `WP-2026-001` |
| `POST`/`PATCH`/`DELETE /work-plans...` | Admin, technical team — assign engineers by ID (`ENG-2026-001`); none = draft |
| `POST /expense-claims` | Logged in — submit your own claim; `amount` or (Travel & Fuel) `distance_km` at `MILEAGE_RATE_PER_KM` |
| `GET /expense-claims?status=&category=&work_plan=&claimant_id=&awaiting_my_action=` | Admin, HR, technical team and owner see all claims; everyone else sees their own |
| `POST /expense-claims/{id}/receipt` | Claimant, while pending — PDF/JPEG/PNG/WebP up to `RECEIPT_MAX_MB` (stored in GridFS) |
| `GET /expense-claims/{id}/receipt` | Claimant, HR, admin |
| `DELETE /expense-claims/{id}` | Claimant — withdraw a pending claim |
| `POST /expense-claims/{id}/approve`, `/reject` | Technical team (pending), then owner (technical-approved); reject needs a `reason` |
| `POST /expense-claims/{id}/reimburse` | HR, once the owner has approved — optional `payment_reference` |

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

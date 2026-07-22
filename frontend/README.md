# Project Tango Frontend

Next.js 15 frontend for the Project Tango LiveKit voice interface.

## Run

```bash
pnpm install
pnpm run dev -- --port 3006
```

Open `http://localhost:3006`.

## Environment

Use `.env.example` as the starting point. FastAPI remains the authority for accounts,
persona policy, and LiveKit room grants. The Next.js server reaches it through a
server-only URL:

```bash
TANGO_INTERNAL_API_BASE_URL=http://127.0.0.1:8030
NEXT_PUBLIC_SITE_URL=http://localhost:3006
```

Browser code calls only same-origin `/api/*` route handlers. Those handlers forward the
session and CSRF cookies, request origin, and request body to FastAPI. Do not reintroduce a
`NEXT_PUBLIC_API_BASE_URL`, direct calls to `tango-api.schubert.life`, or frontend LiveKit
credentials.

The login intentionally accepts only a password. Administrators provision regular accounts at
`/admin`, choose permitted personas, and optionally select an allowlisted per-persona model
override. Generated passwords are returned once after creation or reset and must never be logged
or persisted in browser storage.

Backend contract assumptions used by this frontend:

- `POST /api/auth/login`, `GET /api/auth/me`, and `POST /api/auth/logout`
- `GET /api/personas`, `POST /api/connection-details`, and `POST /api/dispatch`
- `GET /api/admin/personas` and CRUD/action routes below `/api/admin/users`
- `__Host-tango_session` and `__Host-tango_csrf` cookies in production, with non-Host local names
- all authenticated mutations require the CSRF cookie value in `X-CSRF-Token` and the public Origin

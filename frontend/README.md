# Project Tango Frontend

Next.js 15 frontend for the Project Tango LiveKit voice interface.

## Run

```bash
npm install
npm run dev -- --port 3006
```

Open `http://localhost:3006`.

## Environment

Use `.env.example` as the starting point. For Schubert, the frontend should request
session details from the backend:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8030
NEXT_PUBLIC_CONN_DETAILS_ENDPOINT=http://localhost:8030/api/connection-details
```

The persona selector sends the selected persona ID as the `persona` query parameter. The
backend returns LiveKit connection details with persona metadata already embedded in the token.

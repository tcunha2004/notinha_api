# Notinha · API

FastAPI backend for Notinha. Login is "Sign in with Google": the frontend sends the Google ID token to
`POST /auth/google`, the API verifies it and keeps its own session in Redis, delivered in an
`HttpOnly` cookie (`session`, 7 days).

## Run

1. Start Redis from the parent folder (`~/dev/notinha/`):

   ```bash
   docker compose up -d
   ```

2. Create `.env` in this folder:

   | Key               | Required | Default                    |
   | ----------------- | -------- | -------------------------- |
   | `GOOGLE_CLIENT_ID`| yes      |                            |
   | `AWS_REGION`      | yes      |                            |
   | `S3_BUCKET_NAME`  | yes      |                            |
   | `REDIS_URL`       | no       | `redis://localhost:6379/0` |
   | `FRONTEND_ORIGIN` | no       | `http://localhost:5173`    |
   | `COOKIE_SECURE`   | no       | `false` (use `true` on HTTPS) |

3. Start the API (serves on http://localhost:8000):

   ```bash
   uv run fastapi dev src/api/main.py
   ```

## Test

```bash
uv run pytest
```

Tests use `fakeredis` and a patched Google verifier, so they need neither Redis nor network.

## Auth endpoints

| Route              | Result                                                       |
| ------------------ | ------------------------------------------------------------ |
| `POST /auth/google`| Body `{ "credential": "<Google ID token>" }` → user + cookie |
| `GET /auth/me`     | Current user, or 401                                         |
| `POST /auth/logout`| 204, deletes the session and the cookie                      |

When Redis is unreachable, routes that need it answer 503 `{"detail": "Serviço indisponível"}`.

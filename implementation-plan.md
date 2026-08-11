# Implementation Plan — Project Management Dashboard

A dependency-ordered plan: each phase assumes the previous ones are working.
Rough total: 10 phases. Treat phases 1–7 as "must finish for a working MVP",
8–10 as "what makes it a portfolio-grade final project."

---

## Phase 0 — Decisions to lock in before writing code

These are cheap to decide now and expensive to change later.

- **ORM or raw SQL first?** The brief asks you to demonstrate both "with and
  without ORM." Recommendation: build the real app with **SQLAlchemy**
  (2.0 style, `async` engine), and do the "without ORM" version as a
  *separate, small* exercise (Phase 2 has details) rather than maintaining
  two parallel backends forever.
- **Sync vs async FastAPI.** Given S3 calls and DB I/O, use `async def`
  endpoints + `asyncpg`/`SQLAlchemy async` + `aioboto3` (or run boto3 calls
  in a threadpool via `run_in_executor` if you'd rather stick with sync
  boto3 — both are fine for a course project; async end-to-end is more
  impressive).
- **Migrations tool:** Alembic. Set it up in Phase 1, not later — retrofitting
  migrations onto an existing DB is annoying.
- **Password hashing:** `passlib[bcrypt]` or `argon2-cffi`.
- **JWT library:** `python-jose` or `PyJWT`.
- **Local AWS emulation:** use **LocalStack** or **MinIO** (S3-compatible)
  in `docker-compose` so you don't need real AWS credentials during dev.

---

## Phase 1 — Project skeleton & tooling

Goal: `docker compose up` gives you a running (empty) API + Postgres, and
`pytest` runs (even with zero tests).

1. Repo structure:
   ```
   app/
     main.py
     core/          # config, security, dependencies
     models/        # SQLAlchemy models
     schemas/       # Pydantic schemas
     api/           # routers: auth.py, projects.py, documents.py
     services/      # business logic, kept out of routers
     db/            # session, base, migrations (alembic/)
     storage/        # S3 client wrapper
   lambdas/
     resize_image/
     compute_size/
   tests/
   pyproject.toml
   Dockerfile
   docker-compose.yml
   .github/workflows/ci.yml  (or .gitlab-ci.yml)
   ```
2. `pyproject.toml` via **Poetry** (or plain `pip` + `pyproject.toml` +
   `tox.ini` if you prefer): dependencies = fastapi, uvicorn, sqlalchemy,
   asyncpg, alembic, pydantic-settings, python-jose, passlib, boto3/aioboto3,
   pytest, pytest-asyncio, httpx.
3. `core/config.py` — a Pydantic `BaseSettings` class reading env vars
   (DB url, JWT secret, JWT expiry, S3 bucket, AWS creds, max project size).
4. Dockerfile (multi-stage: build deps, then slim runtime image) +
   `docker-compose.yml` with services: `api`, `db` (postgres), `localstack`
   or `minio`.
5. Health check endpoint `GET /health` — first thing you can hit to prove
   the container/DB connection works.
6. `alembic init` and get one empty migration running against the compose DB.

**Checkpoint:** `docker compose up`, `curl localhost:8000/health` → 200.

---

## Phase 2 — Data model & database

Goal: schema exists, migrated, and a raw-SQL version exists
alongside for the "with/without ORM" requirement.

1. Design tables:
   - `users` (id, login, password_hash, created_at)
   - `projects` (id, name, description, owner_id FK→users, created_at)
   - `project_access` (project_id FK, user_id FK, role enum[owner,participant],
     composite PK) — this is your permissions table, and it's why you
     don't just use `projects.owner_id` for access checks: it lets one
     project have many users with roles.
   - `documents` (id, project_id FK, s3_key, filename, content_type,
     size_bytes, uploaded_by FK→users, created_at)
2. Write SQLAlchemy models + relationships (`Project.documents`,
   `Project.access_entries`, `User.projects` via the association table).
3. Alembic migration for all four tables, with FK `ON DELETE CASCADE`
   from `projects` → `documents` and `projects` → `project_access` (this
   gives you "delete project deletes its documents" almost for free at
   the DB level — you still need to delete the S3 objects in application
   code, since cascade only handles rows).
4. **Normalization/denormalization exercise** (explicit Phase-2 requirement):
   - Show the normalized form above (3NF: no repeated groups, access
     is its own table).
   - Add one deliberate denormalization for a documented reason, e.g. a
     `projects.document_count` or `projects.total_size_bytes` counter
     column, updated on upload/delete, to avoid a `COUNT()`/`SUM()` join
     on every `GET /projects`. Write a short note in your README on the
     tradeoff (read speed vs. write complexity/consistency risk).
5. **"Without ORM" deliverable:** a `db/raw/` folder with a `schema.sql`
   (plain DDL, same tables) and 2–3 hand-written parameterized-SQL
   functions (e.g. `get_project_with_documents(conn, project_id)` using
   `asyncpg` directly) to demonstrate you understand what the ORM is
   doing under the hood. This doesn't need to power the real API — a
   short script or a couple of tests exercising it is enough to satisfy
   the requirement.

**Checkpoint:** tables visible via `psql`, seed a row manually, query it back.

---

## Phase 3 — Auth (register, login, JWT)

Goal: `POST /auth`, `POST /login` work; JWT dependency protects routes.

1. Pydantic schemas: `UserCreate` (login, password, repeat_password —
   validate they match with a `model_validator`), `UserLogin`, `UserOut`
   (never return password_hash).
2. `POST /auth`: hash password, insert user, return 201 + `UserOut`.
   Handle duplicate login → 409.
3. `POST /login`: verify password, issue JWT with `sub=user_id`,
   `exp = now + 1h` (per spec). Return `{access_token, token_type}`.
4. `core/security.py`:
   - `create_access_token(user_id)`
   - `get_current_user(token: str = Depends(oauth2_scheme))` — decodes JWT,
     404/401 if invalid/expired, loads user from DB, returns it.
   - This dependency is what every business-logic route will depend on,
     satisfying "all business logic requests authorized via JWT."
5. Wire FastAPI's `OAuth2PasswordBearer` (or a plain `HTTPBearer`) so
   Swagger UI (`/docs`) has a working "Authorize" button — very useful
   for manual testing and for demoing to your mentor.

**Checkpoint:** register a user, log in, get a token, hit a dummy
`GET /me` route that requires the token.

---

## Phase 4 — Projects CRUD + access control

Goal: all `/projects` and `/project/{id}/info` endpoints, with owner vs
participant enforcement.

1. `services/access.py`: a helper `get_user_role(db, project_id, user_id)`
   → `owner | participant | None`, and a dependency factory
   `require_role(min_role)` you can attach to routes. This centralizes
   the permission logic so you're not repeating `if` checks in every route.
2. `POST /projects`: create project row, then create a `project_access`
   row with role=owner for the creator, in the same transaction.
3. `GET /projects`: join `project_access` on current user, return all
   accessible projects with nested documents (this is the "full info"
   requirement — design your Pydantic response model as
   `ProjectOut(details..., documents: list[DocumentOut])`).
4. `GET /project/{id}/info`: 403/404 if no access row exists for user;
   otherwise return details.
5. `PUT /project/{id}/info`: any accessor (owner or participant) can
   update name/description per the "participant = can modify" rule;
   return updated info.
6. `DELETE /project/{id}`: owner-only (403 otherwise). Before deleting
   the row, list its documents, delete each S3 object, then delete the
   project (cascade handles `documents`/`project_access` rows).
7. Consistent error handling: create an `exceptions.py` with
   `NotFoundError`, `ForbiddenError`, and a FastAPI exception handler
   that maps them to proper status codes + JSON bodies, so routes stay
   thin.

**Checkpoint:** full project CRUD lifecycle testable via `/docs`, with a
second test user proving they can't see or delete a project they weren't
invited to.

---

## Phase 5 — Documents & S3

Goal: upload/download/update/delete documents backed by S3.

1. `storage/s3_client.py`: thin wrapper around boto3/aioboto3 —
   `upload(key, file_bytes, content_type)`, `download(key)`, `delete(key)`.
   Point it at LocalStack/MinIO locally via `endpoint_url` config, and at
   real AWS in prod via the same interface.
2. Key naming convention: `projects/{project_id}/{document_id}/{filename}`
   — makes it trivial to find "everything for this project" if you ever
   need to bulk-delete without tracking every key in the DB.
3. `POST /project/{id}/documents`: accept `UploadFile` (single or list),
   validate extension (`.docx`, `.pdf`) and size, stream to S3, insert
   `documents` row(s), return created document metadata.
4. `GET /project/{id}/documents`: list rows for the project (access-checked).
5. `GET /document/{id}`: look up the row, check the requester has access to
   its *parent project* (not just that the doc exists), stream the S3
   object back with correct `Content-Type` / `Content-Disposition` headers.
6. `PUT /document/{id}`: replace the S3 object (same key or new key +
   delete old), update row metadata.
7. `DELETE /document/{id}`: delete S3 object, delete row.
8. **Size limit enforcement:** before/after upload, sum the project's
   document sizes (or read the denormalized counter from Phase 2) and
   reject with 413 if it exceeds the configured limit — this is the
   simplest version of the "apply limit" requirement and doesn't strictly
   need Lambda; Lambda is for the *async* recompute (Phase 7).

**Checkpoint:** upload a real PDF through Swagger, download it back and
diff the bytes, delete it and confirm it's gone from S3 and the DB.

---

## Phase 6 — Sharing / invite

Goal: owners can grant access; optional email-invite flow.

1. `POST /project/{id}/invite?user=<login>`: verify requester is owner
   (403 otherwise), look up target user by login (404 if not found),
   insert a `project_access` row with role=participant (idempotent —
   don't error if they already have access, just no-op or 200).
2. **Optional `GET /project/{id}/share?with=<email>`:**
   - Generate a signed/hashed token (e.g. `itsdangerous.URLSafeTimedSerializer`
     or a JWT with a short custom claim `{project_id, purpose: "invite"}`
     and its own expiry) so the link is tamper-proof and time-limited.
   - Send an email (use a dev-friendly tool like **Mailhog** in
     docker-compose, or just log the link during development instead of
     wiring real SMTP/SES) containing `GET /join?token=...`.
   - `GET /join?token=...`: decode/verify token, if valid create the
     `project_access` row for the *authenticated* user hitting that link
     (they may need to log in first — redirect to login with a `next=`
     param if unauthenticated).

**Checkpoint:** invite a second user, confirm they now see the project in
their `GET /projects`.

---

## Phase 7 — S3 + Lambda (image resize, size calculation)

Goal: an S3 event triggers a Lambda that does async work.

1. Decide the trigger: S3 `ObjectCreated` event on the documents bucket
   (prefix-filtered if you only want it firing on certain paths).
2. **`compute_size` Lambda:** on upload, recompute the sum of a project's
   document sizes and write it back — either directly to Postgres (Lambda
   needs network access to your DB, e.g. via RDS Proxy or a VPC) or,
   simpler for a course project, call back into a small internal API
   endpoint (`POST /internal/projects/{id}/recompute-size`) protected by
   a shared secret, so the Lambda doesn't need direct DB creds.
3. **Image resize Lambda (optional):** if the uploaded doc is an image
   (or you extend scope to support images), generate a thumbnail and
   store it back to S3 under a `thumbnails/` prefix.
4. Local testing: LocalStack supports Lambda + S3 event notifications, so
   you can trigger and debug this without touching real AWS.
5. Package each Lambda with its own minimal `requirements.txt` (keep
   dependencies light — boto3 is already available in the Lambda runtime).
6. IaC (optional but a nice bonus): a small Terraform or AWS SAM template
   defining the bucket, event notification, and Lambda — even if you
   deploy manually for the course, having this documents the setup.

**Checkpoint:** upload a document, watch the Lambda fire in LocalStack
logs, confirm the project's size total updates.

---

## Phase 8 — Testing

Goal: meaningful coverage on the parts most likely to break (auth, access
control, S3 interactions).

1. `pytest` + `pytest-asyncio` + `httpx.AsyncClient` against the FastAPI
   app (use `ASGITransport`, no need to spin up uvicorn for tests).
2. Test DB: a separate Postgres (or the same one, different DB name) spun
   up in CI; run Alembic migrations before the test session, wrap each
   test in a transaction that rolls back (fast, isolated tests).
3. Mock S3 with `moto` (or point at LocalStack in CI) so document tests
   don't need real AWS.
4. Priority test list:
   - register/login happy path + duplicate login + wrong password
   - JWT expiry rejected
   - project CRUD happy paths
   - **access control**: participant can't delete, non-member gets 403/404
     on every project/document route
   - document upload/download round-trip
   - invite flow grants access; non-owner invite is rejected
5. Add `pytest-cov`, target a coverage number you're comfortable citing
   to your mentor (70-80% is a reasonable, honest goal for a course project).

---

## Phase 9 — CI/CD

Goal: push → lint + test + build image; merge to main → deploy.

1. `.github/workflows/ci.yml` (or GitLab CI equivalent) stages:
   - **lint**: `ruff` (fast, covers flake8+isort) + `mypy` if you're typing
     strictly.
   - **test**: spin up postgres + localstack service containers, run
     Alembic migrations, run `pytest --cov`.
   - **build**: `docker build`, tag with git SHA.
   - **push**: push image to a registry (GHCR is easiest with GitHub
     Actions — no extra credentials needed beyond `GITHUB_TOKEN`).
   - **deploy** (on merge to `main` only): whatever target you have —
     could be as simple as SSH + `docker compose pull && up -d` on a VM,
     or a cloud run service. Don't over-engineer this part unless your
     course specifically grades cloud deployment.
2. Use GitHub Actions `matrix` or just pin Python 3.10 to match the spec.
3. Cache Poetry/pip deps between runs to keep CI fast.

---

## Phase 10 — Packaging & polish

1. Make sure `pyproject.toml` fully describes the package (name, version,
   deps split into main/dev groups) so `poetry install` or `pip install .`
   works from a clean clone.
2. `tox.ini` (or `nox`) wrapping lint+test so CI and local dev use the
   identical commands.
3. README: architecture diagram (even a simple one), setup instructions,
   API summary (or link to `/docs`), and the normalization/denormalization
   writeup from Phase 2 — mentors like seeing the reasoning, not just the
   code. All the tool/librarys used and for what purpose.
4. Double-check every response follows the "JSON + correct status code"
   rule from the spec, including error responses (a consistent
   `{"detail": "..."}` shape is fine).

---

## Suggested build order recap

1. Skeleton + Docker + Alembic
2. DB schema (+ normalization notes, + raw-SQL sibling)
3. Auth + JWT
4. Projects CRUD + access control
5. Documents + S3
6. Invite/share
7. Lambda (size calc, optional resize)
8. Tests
9. CI/CD
10. Packaging + README

Each checkpoint above is a good natural place to commit and, if your
course wants incremental check-ins, to show your mentor working progress
rather than a single final drop.

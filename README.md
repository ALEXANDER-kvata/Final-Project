# Project Management Dashboard

FastAPI backend for a project management dashboard with Postgres, JWT authentication,
S3-compatible document storage, and later Lambda-based background processing.

## Phase 1

```powershell
docker compose up --build
```

Then visit:

- API health: http://localhost:8000/health
- OpenAPI docs: http://localhost:8000/docs

Local development uses Postgres and LocalStack through Docker Compose.

## Data Model

Phase 2 uses a normalized relational design:

- `users` stores one row per account.
- `projects` stores project metadata and points to the owning user.
- `project_access` stores project membership and role, so a project can have
  many users without duplicating user or project data.
- `documents` stores document metadata and points to its parent project.

The deliberate denormalization is `projects.total_size_bytes`. The normalized
source of truth is still the `documents.size_bytes` rows, but keeping the total
on `projects` lets the API check project storage limits without running a
`SUM()` over documents on every project read. The tradeoff is that uploads,
deletes, and later the Lambda size recompute need to keep that counter correct.

The real application uses SQLAlchemy models and Alembic migrations. The
`app/db/raw/` folder contains a plain SQL schema plus asyncpg examples for the
course requirement to show the same database work without an ORM.

## Project Endpoints

Phase 4 adds JWT-protected project management endpoints:

- `POST /projects` creates a project and grants the creator the `owner` role.
- `GET /projects` lists projects the current user can access, including nested
  document metadata.
- `GET /project/{project_id}/info` returns one accessible project.
- `PUT /project/{project_id}/info` lets owners or participants edit name and
  description.
- `DELETE /project/{project_id}` is owner-only; it removes every stored object
  for the project before deleting the row (cascade clears the child rows).

## Document Endpoints

Phase 5 stores document content in S3 (LocalStack locally) and keeps only
metadata in Postgres:

- `POST /project/{project_id}/documents` uploads one or more files.
- `GET /project/{project_id}/documents` lists the project's document metadata.
- `GET /document/{document_id}` streams the file back with its original
  `Content-Type` and `Content-Disposition`.
- `PUT /document/{document_id}` replaces the stored file and its metadata.
- `DELETE /document/{document_id}` removes the object and the row.

Every document route authorizes against the document's *parent project*, so a
user with no `project_access` row gets a 404 rather than a leak that the
document exists.

### Storage rules

- Objects are keyed `projects/{project_id}/{document_id}/{filename}`, which
  keeps everything for one project under a single prefix.
- Uploads are validated by extension (`ALLOWED_DOCUMENT_EXTENSIONS`, default
  `.pdf,.docx`) and rejected with 400 when the type is not allowed.
- A single file over `MAX_DOCUMENT_SIZE_BYTES`, or an upload that would push
  `projects.total_size_bytes` past `MAX_PROJECT_SIZE_BYTES`, is rejected with
  413. The limit check reads the denormalized counter from Phase 2 instead of
  summing document rows, and uploads/replacements/deletes keep that counter in
  step. Phase 7 adds the asynchronous Lambda recompute.
- Uploads are transactional: if S3 or the database fails part-way, the rows are
  rolled back and any objects already written are removed.
- The bucket is created on startup if it does not exist, so a fresh LocalStack
  container works without manual setup.

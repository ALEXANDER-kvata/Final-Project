# compute_size Lambda

Triggered by `s3:ObjectCreated:*` under the `projects/` prefix of the documents
bucket. Parses the project id out of the object key
(`projects/{project_id}/{document_id}/{filename}`) and calls back into

```
POST /internal/projects/{project_id}/recompute-size
X-Internal-Secret: <INTERNAL_SHARED_SECRET>
```

which re-sums `documents.size_bytes` for that project and writes the result to
`projects.total_size_bytes`. This is the asynchronous correction path for the
Phase 2 denormalization — the API already keeps the counter right on the
upload/replace/delete happy path; this Lambda is what recovers it from any
drift.

No AWS credentials, database credentials, or third-party dependencies are
needed: the handler only uses `urllib` from the stdlib to make the callback.

## Environment variables

| Name | Purpose |
|---|---|
| `INTERNAL_API_URL` | Base URL of the API, e.g. `http://api:8000` on the compose network |
| `INTERNAL_SHARED_SECRET` | Must match the API's `INTERNAL_SHARED_SECRET` setting |

## Local deployment

`docker-compose.yml` mounts this folder into the `localstack` container and
`docker/localstack-init/ready.d/deploy_lambdas.py` zips and deploys it
automatically on `docker compose up`, along with the S3 bucket notification
that invokes it. Its `print()` output lands in CloudWatch Logs, not the
`localstack` container's own stdout:

```
docker compose exec localstack awslocal logs filter-log-events \
  --log-group-name /aws/lambda/compute_size --query 'events[].message' --output text
```

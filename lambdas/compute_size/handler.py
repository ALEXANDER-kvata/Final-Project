"""S3 ObjectCreated -> recompute a project's document size total.

Deliberately stdlib-only (urllib instead of requests) so this Lambda needs no
dependency packaging step; boto3 is unused too, since the Lambda never talks
to S3 directly, only to the internal API.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

INTERNAL_API_URL = os.environ.get("INTERNAL_API_URL", "http://api:8000").rstrip("/")
INTERNAL_SHARED_SECRET = os.environ.get("INTERNAL_SHARED_SECRET", "")
REQUEST_TIMEOUT_SECONDS = 10


def _project_id_from_key(key: str) -> int | None:
    """Keys look like projects/{project_id}/{document_id}/{filename}."""
    parts = key.split("/")
    if len(parts) < 2 or parts[0] != "projects":
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def _recompute(project_id: int) -> dict:
    url = f"{INTERNAL_API_URL}/internal/projects/{project_id}/recompute-size"
    request = urllib.request.Request(
        url,
        method="POST",
        headers={"X-Internal-Secret": INTERNAL_SHARED_SECRET},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read())


def handler(event: dict, _context: object) -> dict:
    processed = []

    for record in event.get("Records", []):
        raw_key = record.get("s3", {}).get("object", {}).get("key", "")
        key = urllib.parse.unquote_plus(raw_key)
        project_id = _project_id_from_key(key)
        if project_id is None:
            print(f"compute_size: skipping key with no project id: {key}")
            continue

        try:
            result = _recompute(project_id)
        except urllib.error.URLError as exc:
            print(f"compute_size: failed to recompute project {project_id}: {exc}")
            raise

        new_total = result.get("total_size_bytes")
        print(f"compute_size: project {project_id} total_size_bytes={new_total}")
        processed.append(result)

    return {"processed": processed}

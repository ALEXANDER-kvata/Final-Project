# resize_image Lambda

Optional bonus Lambda. Triggered by the same `s3:ObjectCreated:*` /
`projects/` notification as `compute_size`. For any key whose extension is
not a recognized image type, it returns immediately — the endpoint accepts
`.pdf`/`.docx`, so this is a no-op for essentially every upload today and
only does work if the API's allowed extensions are widened to include images.

For image keys, it downloads the object, shrinks it to fit inside 256x256
with Pillow's `Image.thumbnail` (aspect-preserving), and writes the result
back to the same bucket under `thumbnails/{project_id}/{document_id}/{filename}`
— the mirror of the source `projects/{project_id}/{document_id}/{filename}`
key, so thumbnails never collide with source objects or re-trigger either
Lambda (their prefix doesn't match the `projects/` filter).

## Environment

Talks to S3 through `boto3`. When running under LocalStack, `LOCALSTACK_HOSTNAME`
is injected automatically into the Lambda's environment and the handler uses
it to point `boto3` at the LocalStack edge endpoint; in real AWS that variable
is absent and `boto3` falls back to its normal default S3 endpoint.

The pure key/extension logic (`is_image_key`, `thumbnail_key`, no third-party
imports) lives in `logic.py`, separate from `handler.py` which imports `boto3`
and `PIL`. That split is why the test suite can exercise the logic directly
without Pillow or boto3 installed in the main project's environment — they're
only needed inside the Lambda's own deployment zip.

## Local deployment

Packaged and deployed the same way as `compute_size` — see its README. This
one has a real dependency (`Pillow`), so the deploy script `pip install`s
`requirements.txt` into the zip before uploading it, unlike `compute_size`.

Pillow has a compiled C extension (`PIL._imaging`), so it must be installed
for the Lambda runtime's actual platform (`python3.12` on Amazon Linux 2023),
not whatever platform is running the packaging step. The deploy script passes
`--platform manylinux2014_x86_64 --python-version 3.12 --abi cp312
--only-binary=:all:` to pip for exactly this reason — without it, Pillow
installs fine but fails at Lambda import time with
`cannot import name '_imaging' from 'PIL'`.

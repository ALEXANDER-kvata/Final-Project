"""S3 ObjectCreated -> generate a thumbnail for image uploads.

Non-image documents (the common case: PDFs, docx) are skipped immediately, so
this Lambda is a fast no-op for most uploads rather than a second S3 round
trip on every document.
"""

import io
import os
import urllib.parse

import boto3
from logic import THUMBNAIL_MAX_SIZE, is_image_key, thumbnail_key
from PIL import Image


def _s3_client():
    # LocalStack injects LOCALSTACK_HOSTNAME into every Lambda invocation;
    # its absence means this is running against real AWS, where the default
    # boto3 client (no endpoint_url override) is what we want.
    hostname = os.environ.get("LOCALSTACK_HOSTNAME")
    if not hostname:
        return boto3.client("s3")

    edge_port = os.environ.get("EDGE_PORT", "4566")
    return boto3.client("s3", endpoint_url=f"http://{hostname}:{edge_port}")


def handler(event: dict, _context: object) -> dict:
    s3 = _s3_client()
    thumbnails_written = []

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

        if not is_image_key(key):
            print(f"resize_image: skipping non-image key: {key}")
            continue

        dest_key = thumbnail_key(key)
        if dest_key is None:
            print(f"resize_image: skipping key outside the source prefix: {key}")
            continue

        source = s3.get_object(Bucket=bucket, Key=key)
        content_type = source.get("ContentType", "application/octet-stream")

        try:
            image = Image.open(io.BytesIO(source["Body"].read()))
            image_format = image.format or "PNG"
            image.thumbnail(THUMBNAIL_MAX_SIZE)
            buffer = io.BytesIO()
            image.save(buffer, format=image_format)
        except Exception as exc:  # noqa: BLE001 - a corrupt/unsupported image must not crash the Lambda
            print(f"resize_image: could not process {key}: {exc}")
            continue

        s3.put_object(
            Bucket=bucket,
            Key=dest_key,
            Body=buffer.getvalue(),
            ContentType=content_type,
        )
        print(f"resize_image: wrote thumbnail {dest_key} ({buffer.tell()} bytes)")
        thumbnails_written.append(dest_key)

    return {"thumbnails_written": thumbnails_written}

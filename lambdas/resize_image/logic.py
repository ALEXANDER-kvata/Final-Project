"""Pure key/extension logic for the resize_image Lambda.

Split out from handler.py so it has zero third-party imports — this file
alone is what the test suite exercises, without needing boto3 or Pillow
installed in the main project's environment.
"""

from pathlib import PurePosixPath

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
THUMBNAIL_MAX_SIZE = (256, 256)
SOURCE_PREFIX = "projects/"
THUMBNAIL_PREFIX = "thumbnails/"


def is_image_key(key: str) -> bool:
    return PurePosixPath(key).suffix.lower() in IMAGE_EXTENSIONS


def thumbnail_key(key: str) -> str | None:
    if not key.startswith(SOURCE_PREFIX):
        return None
    return THUMBNAIL_PREFIX + key[len(SOURCE_PREFIX) :]

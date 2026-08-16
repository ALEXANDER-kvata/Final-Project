from httpx import AsyncClient

from app.storage.s3_client import build_document_key
from tests.integration.helpers import auth_headers, create_project, register_and_login


async def test_document_upload_download_round_trip(client: AsyncClient) -> None:
    _login, token = await register_and_login(client)
    headers = auth_headers(token)
    project_id = await create_project(client, token)

    content = b"%PDF-1.4 real bytes for the round trip check, not a placeholder\n" * 50

    uploaded = await client.post(
        f"/project/{project_id}/documents",
        headers=headers,
        files={"files": ("report.pdf", content, "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document = uploaded.json()[0]
    assert document["filename"] == "report.pdf"
    assert document["size_bytes"] == len(content)
    assert document["s3_key"] == build_document_key(project_id, document["id"], "report.pdf")

    info = await client.get(f"/project/{project_id}/info", headers=headers)
    assert info.json()["total_size_bytes"] == len(content)

    downloaded = await client.get(f"/document/{document['id']}", headers=headers)
    assert downloaded.status_code == 200
    assert downloaded.content == content  # exact byte-for-byte round trip through real S3
    assert downloaded.headers["content-type"] == "application/pdf"
    assert "report.pdf" in downloaded.headers["content-disposition"]


async def test_document_replace_updates_content_and_size(client: AsyncClient) -> None:
    _login, token = await register_and_login(client)
    headers = auth_headers(token)
    project_id = await create_project(client, token)

    uploaded = await client.post(
        f"/project/{project_id}/documents",
        headers=headers,
        files={"files": ("v1.pdf", b"%PDF-1.4 version one", "application/pdf")},
    )
    document_id = uploaded.json()[0]["id"]

    replacement = b"%PDF-1.4 version two, a fair bit longer than the original content"
    replaced = await client.put(
        f"/document/{document_id}",
        headers=headers,
        files={"file": ("v2.pdf", replacement, "application/pdf")},
    )
    assert replaced.status_code == 200
    assert replaced.json()["filename"] == "v2.pdf"
    assert replaced.json()["size_bytes"] == len(replacement)

    downloaded = await client.get(f"/document/{document_id}", headers=headers)
    assert downloaded.content == replacement

    info = await client.get(f"/project/{project_id}/info", headers=headers)
    assert info.json()["total_size_bytes"] == len(replacement)


async def test_document_delete_removes_it_from_the_api_and_s3(client: AsyncClient) -> None:
    _login, token = await register_and_login(client)
    headers = auth_headers(token)
    project_id = await create_project(client, token)

    uploaded = await client.post(
        f"/project/{project_id}/documents",
        headers=headers,
        files={"files": ("gone.pdf", b"%PDF-1.4 to be deleted", "application/pdf")},
    )
    document_id = uploaded.json()[0]["id"]
    s3_key = uploaded.json()[0]["s3_key"]

    deleted = await client.delete(f"/document/{document_id}", headers=headers)
    assert deleted.status_code == 204

    after = await client.get(f"/document/{document_id}", headers=headers)
    assert after.status_code == 404

    info = await client.get(f"/project/{project_id}/info", headers=headers)
    assert info.json()["total_size_bytes"] == 0

    from app.core.exceptions import NotFoundError
    from app.storage.s3_client import ensure_object_exists

    try:
        await ensure_object_exists(s3_key)
        raised = False
    except NotFoundError:
        raised = True
    assert raised, "the S3 object should have been deleted, not just the database row"


async def test_upload_rejects_disallowed_extension(client: AsyncClient) -> None:
    _login, token = await register_and_login(client)
    headers = auth_headers(token)
    project_id = await create_project(client, token)

    response = await client.post(
        f"/project/{project_id}/documents",
        headers=headers,
        files={"files": ("virus.exe", b"not a real document", "application/octet-stream")},
    )

    assert response.status_code == 400

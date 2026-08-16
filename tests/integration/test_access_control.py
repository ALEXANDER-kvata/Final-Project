"""Access control across every project/document/sharing route.

The app's design choice (documented in README.md) is to return 404 rather
than 403 for a caller with no project_access row at all, so existence isn't
leaked to outsiders. Participants get 403 only on the three owner-only
actions: deleting a project, inviting, and generating a share link.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.integration.helpers import auth_headers, create_project, register_and_login


@pytest_asyncio.fixture
async def scenario(client: AsyncClient) -> dict:
    """One project, one owner, one invited participant, one unrelated stranger."""
    owner_login, owner_token = await register_and_login(client)
    participant_login, participant_token = await register_and_login(client)
    _stranger_login, stranger_token = await register_and_login(client)

    project_id = await create_project(client, owner_token)

    invite = await client.post(
        f"/project/{project_id}/invite",
        headers=auth_headers(owner_token),
        params={"user": participant_login},
    )
    assert invite.status_code == 200, invite.text

    upload = await client.post(
        f"/project/{project_id}/documents",
        headers=auth_headers(owner_token),
        files={"files": ("notes.pdf", b"%PDF-1.4 access control fixture", "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()[0]["id"]

    return {
        "project_id": project_id,
        "document_id": document_id,
        "owner_token": owner_token,
        "participant_token": participant_token,
        "stranger_token": stranger_token,
    }


NON_MEMBER_ROUTES = [
    ("GET", "/project/{project_id}/info"),
    ("PUT", "/project/{project_id}/info"),
    ("DELETE", "/project/{project_id}"),
    ("GET", "/project/{project_id}/documents"),
    ("POST", "/project/{project_id}/documents"),
    ("GET", "/document/{document_id}"),
    ("PUT", "/document/{document_id}"),
    ("DELETE", "/document/{document_id}"),
    ("POST", "/project/{project_id}/invite"),
    ("GET", "/project/{project_id}/share"),
]


@pytest.mark.parametrize(("method", "path_template"), NON_MEMBER_ROUTES)
async def test_non_member_gets_404_on_every_route(
    client: AsyncClient, scenario: dict, method: str, path_template: str
) -> None:
    path = path_template.format(**scenario)
    headers = auth_headers(scenario["stranger_token"])
    kwargs = {}
    if path_template.endswith("/invite"):
        kwargs["params"] = {"user": "irrelevant"}
    elif path_template.endswith("/share"):
        kwargs["params"] = {"with": "irrelevant@example.com"}
    elif method in ("POST", "PUT") and "/document" in path_template:
        field = "file" if method == "PUT" else "files"
        kwargs["files"] = {field: ("x.pdf", b"data", "application/pdf")}

    response = await client.request(method, path, headers=headers, **kwargs)

    assert response.status_code == 404, (
        f"{method} {path} -> {response.status_code}: {response.text}"
    )


async def test_participant_cannot_delete_the_project(client: AsyncClient, scenario: dict) -> None:
    response = await client.delete(
        f"/project/{scenario['project_id']}", headers=auth_headers(scenario["participant_token"])
    )

    assert response.status_code == 403


async def test_participant_cannot_invite(client: AsyncClient, scenario: dict) -> None:
    response = await client.post(
        f"/project/{scenario['project_id']}/invite",
        headers=auth_headers(scenario["participant_token"]),
        params={"user": "someone"},
    )

    assert response.status_code == 403


async def test_participant_cannot_generate_a_share_link(
    client: AsyncClient, scenario: dict
) -> None:
    response = await client.get(
        f"/project/{scenario['project_id']}/share",
        headers=auth_headers(scenario["participant_token"]),
        params={"with": "someone@example.com"},
    )

    assert response.status_code == 403


async def test_participant_can_read_and_modify_project_info(
    client: AsyncClient, scenario: dict
) -> None:
    headers = auth_headers(scenario["participant_token"])

    info = await client.get(f"/project/{scenario['project_id']}/info", headers=headers)
    assert info.status_code == 200

    updated = await client.put(
        f"/project/{scenario['project_id']}/info",
        headers=headers,
        json={"name": "Edited by participant"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Edited by participant"


async def test_participant_can_manage_documents(client: AsyncClient, scenario: dict) -> None:
    headers = auth_headers(scenario["participant_token"])

    listed = await client.get(f"/project/{scenario['project_id']}/documents", headers=headers)
    assert listed.status_code == 200

    downloaded = await client.get(f"/document/{scenario['document_id']}", headers=headers)
    assert downloaded.status_code == 200

    deleted = await client.delete(f"/document/{scenario['document_id']}", headers=headers)
    assert deleted.status_code == 204

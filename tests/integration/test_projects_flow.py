from httpx import AsyncClient

from tests.integration.helpers import auth_headers, create_project, register_and_login


async def test_project_full_crud_lifecycle(client: AsyncClient) -> None:
    _login, token = await register_and_login(client)
    headers = auth_headers(token)

    created = await client.post(
        "/projects", headers=headers, json={"name": "Lifecycle", "description": "v1"}
    )
    assert created.status_code == 201
    project_id = created.json()["id"]
    assert created.json()["owner_id"] is not None
    assert created.json()["documents"] == []

    listed = await client.get("/projects", headers=headers)
    assert listed.status_code == 200
    assert project_id in [p["id"] for p in listed.json()]

    info = await client.get(f"/project/{project_id}/info", headers=headers)
    assert info.status_code == 200
    assert info.json()["name"] == "Lifecycle"

    updated = await client.put(
        f"/project/{project_id}/info", headers=headers, json={"name": "Renamed"}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["description"] == "v1"  # untouched field survives a partial update

    deleted = await client.delete(f"/project/{project_id}", headers=headers)
    assert deleted.status_code == 204

    after_delete = await client.get(f"/project/{project_id}/info", headers=headers)
    assert after_delete.status_code == 404


async def test_creator_becomes_owner_with_full_access(client: AsyncClient) -> None:
    _login, token = await register_and_login(client)
    headers = auth_headers(token)

    project_id = await create_project(client, token)

    delete_response = await client.delete(f"/project/{project_id}", headers=headers)

    assert delete_response.status_code == 204  # owner-only action, and it worked

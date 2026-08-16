from httpx import AsyncClient

from tests.integration.helpers import auth_headers, create_project, register_and_login


async def test_invite_grants_access_and_shows_in_project_list(client: AsyncClient) -> None:
    owner_login, owner_token = await register_and_login(client)
    guest_login, guest_token = await register_and_login(client)
    project_id = await create_project(client, owner_token)

    before = await client.get("/projects", headers=auth_headers(guest_token))
    assert project_id not in [p["id"] for p in before.json()]

    invite = await client.post(
        f"/project/{project_id}/invite",
        headers=auth_headers(owner_token),
        params={"user": guest_login},
    )
    assert invite.status_code == 200
    assert invite.json()["role"] == "participant"
    assert invite.json()["created"] is True

    after = await client.get("/projects", headers=auth_headers(guest_token))
    assert project_id in [p["id"] for p in after.json()]


async def test_repeat_invite_is_idempotent(client: AsyncClient) -> None:
    _owner_login, owner_token = await register_and_login(client)
    guest_login, _guest_token = await register_and_login(client)
    project_id = await create_project(client, owner_token)
    headers = auth_headers(owner_token)

    first = await client.post(
        f"/project/{project_id}/invite", headers=headers, params={"user": guest_login}
    )
    second = await client.post(
        f"/project/{project_id}/invite", headers=headers, params={"user": guest_login}
    )

    assert first.status_code == 200 and first.json()["created"] is True
    assert second.status_code == 200 and second.json()["created"] is False


async def test_non_owner_invite_is_rejected(client: AsyncClient) -> None:
    _owner_login, owner_token = await register_and_login(client)
    participant_login, participant_token = await register_and_login(client)
    _target_login, _target_token = await register_and_login(client)
    project_id = await create_project(client, owner_token)

    await client.post(
        f"/project/{project_id}/invite",
        headers=auth_headers(owner_token),
        params={"user": participant_login},
    )

    rejected = await client.post(
        f"/project/{project_id}/invite",
        headers=auth_headers(participant_token),
        params={"user": _target_login},
    )

    assert rejected.status_code == 403


async def test_invite_of_unknown_login_is_rejected(client: AsyncClient) -> None:
    _owner_login, owner_token = await register_and_login(client)
    project_id = await create_project(client, owner_token)

    response = await client.post(
        f"/project/{project_id}/invite",
        headers=auth_headers(owner_token),
        params={"user": "no-such-user-exists"},
    )

    assert response.status_code == 404


async def test_share_link_grants_access_when_joined(client: AsyncClient) -> None:
    _owner_login, owner_token = await register_and_login(client)
    _guest_login, guest_token = await register_and_login(client)
    project_id = await create_project(client, owner_token)

    share = await client.get(
        f"/project/{project_id}/share",
        headers=auth_headers(owner_token),
        params={"with": "guest@example.com"},
    )
    assert share.status_code == 200
    token = share.json()["invite_url"].rsplit("token=", 1)[1]

    joined = await client.get("/join", headers=auth_headers(guest_token), params={"token": token})
    assert joined.status_code == 200
    assert joined.json()["role"] == "participant"

    projects = await client.get("/projects", headers=auth_headers(guest_token))
    assert project_id in [p["id"] for p in projects.json()]


async def test_join_with_tampered_token_is_rejected(client: AsyncClient) -> None:
    _owner_login, owner_token = await register_and_login(client)
    _guest_login, guest_token = await register_and_login(client)
    project_id = await create_project(client, owner_token)

    share = await client.get(
        f"/project/{project_id}/share",
        headers=auth_headers(owner_token),
        params={"with": "guest@example.com"},
    )
    token = share.json()["invite_url"].rsplit("token=", 1)[1]

    response = await client.get(
        "/join", headers=auth_headers(guest_token), params={"token": token + "x"}
    )

    assert response.status_code == 400

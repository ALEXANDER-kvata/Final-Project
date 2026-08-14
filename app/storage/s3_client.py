async def delete_object(_key: str) -> None:
    """Phase 5 will replace this with the real S3 delete call."""


async def delete_objects(keys: list[str]) -> None:
    for key in keys:
        await delete_object(key)

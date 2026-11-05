"""Seal every stored secret again with the current SECRET_KEY, after a rotation:
    SECRET_KEY=<new> SECRET_KEY_PREVIOUS=<old> python -m chatfront.core.reseal
Each value is opened with whichever key works and sealed with the new one, in one
transaction. Running it twice does no harm.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from chatfront.core.db import Database
from chatfront.core.secretbox import remember_previous, seal, unseal
from chatfront.core.settings import get_settings

# (table, column) of every sealed value.
SEALED = (
    ("tenants", "receipt_key_sealed"),
    ("channel_accounts", "access_token_sealed"),
    ("customer_identities", "external_sealed"),
    ("commerce_catalogs", "access_token_sealed"),
    ("courier_accounts", "token_sealed"),
    ("wallet_credits", "body_sealed"),
    ("store_connections", "key_sealed"),
    ("store_connections", "secret_sealed"),
)


async def reseal(db: Database, key: str) -> int:
    done = 0
    async with db.system() as session:
        for table, column in SEALED:
            rows = await session.execute(
                text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")  # noqa: S608
            )
            for row_id, value in rows.all():
                await session.execute(
                    text(f"UPDATE {table} SET {column} = :v WHERE id = :id"),  # noqa: S608
                    {"v": seal(unseal(value, key), key), "id": row_id},
                )
                done += 1
    return done


async def _main() -> None:
    settings = get_settings()
    previous = settings.secret_key_previous
    remember_previous([previous.get_secret_value()] if previous else [])
    db = Database(settings.database_url, pool_size=1)
    try:
        count = await reseal(db, settings.secret_key.get_secret_value())
    finally:
        await db.dispose()
    print(f"Sealed {count} secrets with the current key.")


if __name__ == "__main__":
    asyncio.run(_main())

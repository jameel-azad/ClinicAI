import asyncio
from sqlalchemy import text
from app.database import engine


async def flush():
    async with engine.begin() as conn:
        await conn.execute(text("SET session_replication_role = replica"))
        result = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        tables = [row[0] for row in result.fetchall()]
        for table in tables:
            await conn.execute(text(f'TRUNCATE TABLE "{table}" CASCADE'))
            print(f"  Truncated: {table}")
        await conn.execute(text("SET session_replication_role = DEFAULT"))
    print("DB flushed.")


asyncio.run(flush())

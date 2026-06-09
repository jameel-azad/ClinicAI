"""
Reset the PostgreSQL database for clean testing.
Drops and recreates the public schema, then re-creates all tables via SQLAlchemy.
Run from D:\\ClinicAI:
    .venv\\Scripts\\python.exe scripts/reset_db.py
"""
import asyncio
import os
import sys

sys.path.insert(0, ".")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://clinicai:password@localhost:5432/clinicai")


async def reset():
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    db_url = os.environ["DATABASE_URL"]

    # Step 1: Drop and recreate the public schema
    engine = create_async_engine(db_url, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO clinicai"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
    await engine.dispose()
    print("[1] Schema dropped and recreated — all data wiped")

    # Step 2: Recreate all tables via SQLAlchemy models (same as app lifespan)
    from app.database import Base
    import app.models  # noqa — registers all models with Base
    engine2 = create_async_engine(db_url, echo=False)
    async with engine2.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine2.dispose()
    print("[2] All tables recreated from SQLAlchemy models")


if __name__ == "__main__":
    asyncio.run(reset())

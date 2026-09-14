"""Database connection and management."""

import asyncio
from functools import lru_cache
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from aso_node_recovery.config import settings


class Database:
    """Async database manager using SQLAlchemy with SQLite."""

    def __init__(self, db_path: str | None = None):
        """Initialize database.

        Args:
            db_path: Path to SQLite database file. If None, uses settings.
        """
        self.db_path = db_path or settings.database.path
        self._engine: AsyncEngine | None = None
        self._session_maker: async_sessionmaker[AsyncSession] | None = None
        self._initialized = False
        self._lock = asyncio.Lock()

    @property
    def engine(self) -> AsyncEngine:
        """Get database engine."""
        if self._engine is None:
            raise RuntimeError("Database not initialized")
        return self._engine

    @property
    def session_maker(self) -> async_sessionmaker[AsyncSession]:
        """Get session maker."""
        if self._session_maker is None:
            raise RuntimeError("Database not initialized")
        return self._session_maker

    async def initialize(self) -> None:
        """Initialize database connection and create tables."""
        async with self._lock:
            if self._initialized:
                return

            # Ensure directory exists
            db_file = Path(self.db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)

            # Create async engine
            self._engine = create_async_engine(
                f"sqlite+aiosqlite:///{self.db_path}",
                echo=settings.debug,
                future=True,
            )

            # Create session maker
            self._session_maker = async_sessionmaker(
                self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            # Create tables
            await self._create_tables()

            self._initialized = True

    async def _create_tables(self) -> None:
        """Create database tables."""
        from aso_node_recovery.database import models  # noqa: F401 - Import models to register them

        async with self._engine.begin() as conn:
            # Run migrations
            await conn.run_sync(models.Base.metadata.create_all)

    async def close(self) -> None:
        """Close database connection."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_maker = None
            self._initialized = False

    async def health_check(self) -> bool:
        """Check database health."""
        try:
            async with self.engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def get_session(self) -> AsyncSession:
        """Get a database session."""
        if not self._initialized:
            await self.initialize()
        return self.session_maker()


@lru_cache
def get_database() -> Database:
    """Get cached database instance."""
    return Database()


async def init_database(db_path: str | None = None) -> Database:
    """Initialize and return database instance."""
    db = get_database()
    if db_path:
        db.db_path = db_path
    await db.initialize()
    return db

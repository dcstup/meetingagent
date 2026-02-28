import asyncio
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import JSON
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.dialects.postgresql import JSONB

from src.models import Base
from src.models.tables import Workspace, MeetingSession, MeetingStatus


def _remap_jsonb_to_json():
    """Mutate JSONB columns to JSON so SQLite can handle them."""
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()


_remap_jsonb_to_json()


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_factory(db_engine):
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session(db_session_factory):
    async with db_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def app(db_engine, db_session_factory):
    """Create a test FastAPI app wired to the in-memory DB."""
    from src.db.session import get_db

    async def _override_get_db():
        async with db_session_factory() as session:
            yield session

    with patch("src.db.engine.engine", db_engine), \
         patch("src.db.engine.async_session", db_session_factory), \
         patch("src.workers.calendar_poll.poll_calendar_events", new_callable=AsyncMock):
        from src.api.app import create_app
        test_app = create_app()
        test_app.dependency_overrides[get_db] = _override_get_db
        yield test_app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def workspace(db_session):
    ws = Workspace(
        webhook_secret="test-webhook-secret",
        overlay_token="test-overlay-token",
        composio_entity_id="test-entity",
    )
    db_session.add(ws)
    await db_session.commit()
    await db_session.refresh(ws)
    return ws


@pytest_asyncio.fixture
async def active_session(db_session, workspace):
    session = MeetingSession(
        workspace_id=workspace.id,
        recall_bot_id="test-bot-123",
        meet_url="https://meet.google.com/abc-defg-hij",
        status=MeetingStatus.bot_joining,
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session

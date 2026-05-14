from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from rag_common.config import Settings, get_settings


@lru_cache
def get_engine(database_url: str | None = None) -> Engine:
    settings = get_settings()
    url = database_url or settings.database_url
    return create_engine(url, pool_pre_ping=True, future=True)


@lru_cache
def get_sessionmaker(database_url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url), autoflush=False, expire_on_commit=False)


def session_scope(settings: Settings | None = None) -> Generator[Session]:
    maker = get_sessionmaker(settings.database_url if settings else None)
    session = maker()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database() -> bool:
    with get_engine().connect() as connection:
        connection.execute(text("select 1"))
    return True

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from rag_common.config import Settings, get_settings
from rag_common.db.session import get_sessionmaker
from sqlalchemy.orm import Session

security = HTTPBearer(auto_error=False)


def settings_dep() -> Settings:
    return get_settings()


type SettingsDep = Annotated[Settings, Depends(settings_dep)]


def db_session(settings: SettingsDep) -> Generator[Session]:
    maker = get_sessionmaker(settings.database_url)
    session = maker()
    try:
        yield session
    finally:
        session.close()


def require_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    settings: SettingsDep,
) -> None:
    expected = settings.api_bearer_token.get_secret_value()
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.credentials != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid bearer token",
        )


type DbSession = Annotated[Session, Depends(db_session)]
type AuthDep = Annotated[None, Depends(require_bearer_token)]

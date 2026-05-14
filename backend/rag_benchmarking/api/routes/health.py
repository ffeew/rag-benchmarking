import redis
from fastapi import APIRouter
from minio.error import S3Error
from rag_common.db.session import check_database
from rag_common.schemas import ReadinessResponse
from rag_common.storage.minio import ObjectStore
from sqlalchemy.exc import SQLAlchemyError

from rag_benchmarking.api.deps import SettingsDep

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(settings: SettingsDep) -> ReadinessResponse:
    database = False
    minio = False
    redis_ok = False
    try:
        database = check_database()
    except SQLAlchemyError:
        database = False
    try:
        ObjectStore(settings).ensure_buckets()
        minio = True
    except (OSError, S3Error, ValueError):
        minio = False
    try:
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        redis_ok = bool(client.ping())
    except (redis.RedisError, OSError):
        redis_ok = False
    providers = {
        "allow_mock_providers": settings.allow_mock_providers,
        "openrouter_chat_model": settings.openrouter_chat_model,
        "openrouter_embedding_model": settings.openrouter_embedding_model,
        "openrouter_rerank_model": settings.openrouter_rerank_model,
        "mistral_ocr_model": settings.mistral_ocr_model,
    }
    all_ready = database and minio and redis_ok
    return ReadinessResponse(
        status="ready" if all_ready else "degraded",
        database=database,
        minio=minio,
        redis=redis_ok,
        providers=providers,
    )

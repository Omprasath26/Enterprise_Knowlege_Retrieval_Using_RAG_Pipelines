
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.documents import router as documents_router
from app.api.routes.health import router as health_router
from app.core.config import get_settings
from app.services.document_repository import initialize_database


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize application resources during startup."""

    initialize_database()

    yield

    # Application shutdown cleanup can be added here later.


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)


app.include_router(
    health_router,
    prefix=settings.api_prefix,
)

app.include_router(
    documents_router,
    prefix=f"{settings.api_prefix}/documents",
)


@app.get("/", tags=["Root"])
def root() -> dict[str, str]:
    """Provide basic API information."""

    return {
        "message": settings.app_name,
        "status": "running",
        "health_endpoint": f"{settings.api_prefix}/health",
    }

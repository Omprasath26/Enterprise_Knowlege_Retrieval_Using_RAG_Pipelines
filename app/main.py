
from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
)

app.include_router(
    health_router,
    prefix=settings.api_prefix,
)


@app.get("/", tags=["Root"])
def root() -> dict[str, str]:
    """Provide basic API information."""
    return {
        "message": settings.app_name,
        "status": "running",
        "health_endpoint": f"{settings.api_prefix}/health",
    }

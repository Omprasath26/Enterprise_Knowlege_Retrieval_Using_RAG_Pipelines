
from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    """Confirm that the API application is responding."""
    return {"status": "healthy"}

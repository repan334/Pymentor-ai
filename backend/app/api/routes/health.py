from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Check API process health",
)
async def health() -> HealthResponse:
    """Report that the API process can serve requests; no dependencies are probed."""
    return HealthResponse()

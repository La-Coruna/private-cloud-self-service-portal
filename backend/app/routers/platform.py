from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import get_platform_status_service
from app.domain import PlatformAvailability
from app.services.platform_status import PlatformStatusService


router = APIRouter(prefix="/api/platform-status", tags=["platform"])


class PlatformStatusResponse(BaseModel):
    status: PlatformAvailability
    message: str
    creation_allowed: bool
    checked_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=PlatformStatusResponse)
def get_platform_status(
    service: PlatformStatusService = Depends(get_platform_status_service),
):
    return service.get_status()

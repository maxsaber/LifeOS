"""
Briefings API endpoints.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from api.services.briefings import get_briefings_service

router = APIRouter(prefix="/api", tags=["briefings"])


class BriefingRequest(BaseModel):
    """Request for stakeholder briefing."""
    person_name: str
    email: Optional[str] = None  # v2: Optional email for better resolution


class BriefingResponse(BaseModel):
    """Response with stakeholder briefing."""
    status: str
    briefing: Optional[str] = None
    message: Optional[str] = None
    person_name: str
    metadata: Optional[dict] = None
    sources: Optional[list[str]] = None
    action_items_count: Optional[int] = None
    notes_count: Optional[int] = None


@router.post("/briefing", response_model=BriefingResponse)
async def get_briefing(request: BriefingRequest) -> BriefingResponse:
    """
    Generate a stakeholder briefing for a person.

    This aggregates all context about a person from:
    - People metadata (LinkedIn, Gmail, Calendar)
    - Vault notes mentioning them
    - Action items involving them
    - Interaction history (v2)
    """
    if not request.person_name.strip():
        raise HTTPException(status_code=400, detail="Person name cannot be empty")

    service = get_briefings_service()
    result = await service.generate_briefing(request.person_name, email=request.email)

    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))

    return BriefingResponse(**result)


@router.get("/briefing/{person_name}", response_model=BriefingResponse)
async def get_briefing_by_name(
    person_name: str,
    email: Optional[str] = Query(default=None, description="Optional email for better resolution")
) -> BriefingResponse:
    """
    Generate a stakeholder briefing by person name (URL path).

    Convenience endpoint for "tell me about X" style queries.
    """
    if not person_name.strip():
        raise HTTPException(status_code=400, detail="Person name cannot be empty")

    service = get_briefings_service()
    result = await service.generate_briefing(person_name, email=email)

    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))

    return BriefingResponse(**result)

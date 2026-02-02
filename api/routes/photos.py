"""
Apple Photos API endpoints for LifeOS.

Provides endpoints for querying Photos face recognition data
and syncing to LifeOS CRM.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from config.settings import settings

router = APIRouter(prefix="/api/photos", tags=["photos"])


class PhotoResponse(BaseModel):
    """Response model for a photo."""
    uuid: str
    timestamp: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source_link: str


class PhotosForPersonResponse(BaseModel):
    """Response for photos of a person."""
    person_id: str
    photos: list[PhotoResponse]
    count: int


class CoAppearanceResponse(BaseModel):
    """Response for co-appearance data."""
    person_a_id: str
    person_b_id: str
    shared_photo_count: int
    photos: list[PhotoResponse]


class PhotosPersonResponse(BaseModel):
    """Response for a Photos person."""
    pk: int
    full_name: str
    display_name: Optional[str] = None
    face_count: int
    has_contact_link: bool
    matched_entity_id: Optional[str] = None


class PhotosStatsResponse(BaseModel):
    """Response for Photos statistics."""
    total_named_people: int
    people_with_contacts: int
    total_face_detections: int
    multi_person_photos: int
    photos_enabled: bool


class SyncResponse(BaseModel):
    """Response for sync operation."""
    success: bool
    stats: dict
    message: str


def _check_photos_enabled():
    """Check if Photos integration is available."""
    if not settings.photos_enabled:
        raise HTTPException(
            status_code=503,
            detail="Photos integration not available. Photos library not mounted or accessible."
        )


@router.get("/stats", response_model=PhotosStatsResponse)
async def get_photos_stats():
    """
    Get statistics about the Photos library.

    Returns counts of named people, face detections, and multi-person photos.
    """
    if not settings.photos_enabled:
        return PhotosStatsResponse(
            total_named_people=0,
            people_with_contacts=0,
            total_face_detections=0,
            multi_person_photos=0,
            photos_enabled=False,
        )

    try:
        from api.services.apple_photos import get_apple_photos_reader

        reader = get_apple_photos_reader()
        stats = reader.get_stats()

        return PhotosStatsResponse(
            total_named_people=stats.get("total_named_people", 0),
            people_with_contacts=stats.get("people_with_contacts", 0),
            total_face_detections=stats.get("total_face_detections", 0),
            multi_person_photos=stats.get("multi_person_photos", 0),
            photos_enabled=True,
        )
    except FileNotFoundError:
        return PhotosStatsResponse(
            total_named_people=0,
            people_with_contacts=0,
            total_face_detections=0,
            multi_person_photos=0,
            photos_enabled=False,
        )


@router.get("/people", response_model=list[PhotosPersonResponse])
async def list_photos_people(
    linked_only: bool = Query(
        default=True,
        description="Only return people linked to Apple Contacts"
    ),
    limit: int = Query(default=100, ge=1, le=500),
):
    """
    List people recognized in Photos.

    Returns face recognition data from Apple Photos with optional
    filtering for people linked to Contacts (more reliable matching).
    """
    _check_photos_enabled()

    from api.services.apple_photos import get_apple_photos_reader
    from api.services.apple_photos_sync import ApplePhotosSync

    reader = get_apple_photos_reader()

    if linked_only:
        people = reader.get_people_with_contacts()
    else:
        people = reader.get_all_people()

    # Match to PersonEntity
    syncer = ApplePhotosSync(photos_reader=reader)
    results = []

    for person in people[:limit]:
        entity_id = None
        if person.person_uri:
            entity_id = syncer.match_photos_person_to_entity(person)

        results.append(PhotosPersonResponse(
            pk=person.pk,
            full_name=person.full_name,
            display_name=person.display_name,
            face_count=person.face_count,
            has_contact_link=person.person_uri is not None,
            matched_entity_id=entity_id,
        ))

    return results


@router.get("/person/{person_id}", response_model=PhotosForPersonResponse)
async def get_photos_for_person(
    person_id: str,
    limit: int = Query(default=50, ge=1, le=200),
):
    """
    Get photos containing a specific person.

    Requires a LifeOS PersonEntity ID. Returns photos where this
    person's face was recognized.
    """
    _check_photos_enabled()

    from api.services.interaction_store import get_interaction_store

    interaction_store = get_interaction_store()

    # Get photo interactions for this person
    interactions = interaction_store.get_for_person(
        person_id,
        source_type="photos",
    )

    photos = []
    for interaction in interactions[:limit]:
        photos.append(PhotoResponse(
            uuid=interaction.source_id or "",
            timestamp=interaction.timestamp.isoformat() if interaction.timestamp else None,
            latitude=None,  # Not stored in interaction
            longitude=None,
            source_link=interaction.source_link,
        ))

    return PhotosForPersonResponse(
        person_id=person_id,
        photos=photos,
        count=len(photos),
    )


@router.get("/shared/{person_a_id}/{person_b_id}", response_model=CoAppearanceResponse)
async def get_shared_photos(
    person_a_id: str,
    person_b_id: str,
    limit: int = Query(default=20, ge=1, le=100),
):
    """
    Get photos where two people appear together.

    Returns photos where both people's faces were recognized.
    """
    _check_photos_enabled()

    from api.services.interaction_store import get_interaction_store

    interaction_store = get_interaction_store()

    # Get photo interactions for both people
    photos_a = interaction_store.get_for_person(person_a_id, source_type="photos")
    photos_b = interaction_store.get_for_person(person_b_id, source_type="photos")

    # Find shared photos by source_id (asset UUID)
    uuids_a = {i.source_id for i in photos_a if i.source_id}
    shared_uuids = {i.source_id for i in photos_b if i.source_id and i.source_id in uuids_a}

    # Get details for shared photos
    photos = []
    for interaction in photos_a:
        if interaction.source_id in shared_uuids and len(photos) < limit:
            photos.append(PhotoResponse(
                uuid=interaction.source_id or "",
                timestamp=interaction.timestamp.isoformat() if interaction.timestamp else None,
                latitude=None,
                longitude=None,
                source_link=interaction.source_link,
            ))

    return CoAppearanceResponse(
        person_a_id=person_a_id,
        person_b_id=person_b_id,
        shared_photo_count=len(shared_uuids),
        photos=photos,
    )


@router.post("/sync", response_model=SyncResponse)
async def trigger_photo_sync(
    incremental: bool = Query(
        default=True,
        description="If true, only sync new photos since last sync"
    ),
):
    """
    Trigger Photos sync to LifeOS CRM.

    Creates SourceEntity and Interaction records for matched people
    in Photos face recognition data.
    """
    _check_photos_enabled()

    from api.services.apple_photos_sync import sync_apple_photos

    try:
        # For now, always do full sync (incremental requires tracking state)
        stats = sync_apple_photos(since=None)

        return SyncResponse(
            success=True,
            stats=stats,
            message=f"Synced {stats.get('person_matches', 0)} people, "
                    f"created {stats.get('interactions_created', 0)} interactions"
        )
    except Exception as e:
        return SyncResponse(
            success=False,
            stats={"error": str(e)},
            message=f"Sync failed: {e}"
        )

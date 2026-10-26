from datetime import datetime

from pydantic import BaseModel, Field

from app.models.common import LabeledEnum, StrictModel


class PlaceType(LabeledEnum):
    WORKSHOP = "workshop", "Workshop"
    HOTEL = "hotel", "Hotel"
    VESSEL = "vessel", "Vessel"
    AIRPORT = "airport", "Airport"
    CUSTOMER_SITE = "customer_site", "Customer Site"
    OTHER = "other", "Other"


class CheckInCreate(StrictModel):
    """Where the engineer is now, typed in by them (no location tracking)."""

    place_type: PlaceType
    place_name: str = Field(min_length=1, max_length=200)  # e.g. "Hilton Rotterdam", "MV Ocean Star", "SIN T3"
    note: str | None = Field(default=None, max_length=500)


class CheckInOut(BaseModel):
    id: str
    engineer_id: str
    full_name: str | None = None
    place_type: PlaceType
    place_name: str
    note: str | None = None
    checked_in_at: datetime

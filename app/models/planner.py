from datetime import date

from pydantic import BaseModel, Field

from app.models.common import LabeledEnum, StrictModel
from app.models.territory import Territory
from app.models.work_plan import EngineerId


class DayStatus(LabeledEnum):
    WORKSHOP = "workshop", "Workshop"
    SHIP = "ship", "Ship"
    TRAVEL = "travel", "Travel"
    LEAVE = "leave", "Leave"
    DAY_OFF = "day_off", "Day Off"
    STANDBY = "standby", "Standby"


# Letter and colour shown on the planner grid.
DAY_STATUS_STYLE: dict[DayStatus, tuple[str, str]] = {
    DayStatus.WORKSHOP: ("W", "green"),
    DayStatus.SHIP: ("W", "deep_green"),
    DayStatus.TRAVEL: ("T", "blue"),
    DayStatus.LEAVE: ("L", "rose"),
    DayStatus.DAY_OFF: ("D", "purple"),
    DayStatus.STANDBY: ("S", "orange"),
}

# Days an engineer can take on new work. Days with no entry also count as available.
AVAILABLE_DAY_STATUSES = {DayStatus.WORKSHOP, DayStatus.STANDBY}


class MonthStatus(LabeledEnum):
    OFF = "off", "Month Off"
    ON_CALL = "on_call", "On Call"


# ---- Requests ----


class DayEntry(StrictModel):
    engineer_id: EngineerId
    date: date
    # null removes the whole entry for that day (status, note and work order).
    status: DayStatus | None
    note: str | None = Field(default=None, max_length=500)
    # Work order id or number (e.g. WO-2026-001); the engineer must be on its crew.
    work_order: str | None = None


class DayEntriesUpdate(StrictModel):
    entries: list[DayEntry] = Field(min_length=1, max_length=1000)


class EngineerPlannerUpdate(StrictModel):
    current_country: str | None = Field(default=None, max_length=100)
    planner_comment: str | None = Field(default=None, max_length=500)


class MonthEntry(StrictModel):
    engineer_id: EngineerId
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    # null clears the month.
    status: MonthStatus | None
    note: str | None = Field(default=None, max_length=500)


class MonthEntriesUpdate(StrictModel):
    entries: list[MonthEntry] = Field(min_length=1, max_length=1000)


class EntriesSaved(BaseModel):
    saved: int
    cleared: int


# ---- Responses ----


class PlannerWorkOrder(BaseModel):
    id: str
    work_order_number: str
    title: str
    customer: str | None = None


class DayCell(BaseModel):
    status: DayStatus | None = None
    note: str | None = None
    work_order: PlannerWorkOrder | None = None
    available: bool  # free for new work: Workshop/Standby or nothing planned, and not a month off


class PlannerEngineer(BaseModel):
    engineer_id: str
    user_id: str
    full_name: str | None = None
    skills: list[str] = []
    territory: Territory | None = None
    current_country: str | None = None
    planner_comment: str | None = None
    days: dict[date, DayCell]
    work_orders: list[PlannerWorkOrder] = []  # distinct work orders in the range, for the weekly view


class DayPlanner(BaseModel):
    today: date
    start: date
    end: date
    dates: list[date]
    engineers: list[PlannerEngineer]
    totals: dict[date, dict[DayStatus, int]]  # per day: how many engineers have each status


class EngineerAvailability(BaseModel):
    engineer_id: str
    full_name: str | None = None
    available_dates: list[date]


class MonthCell(BaseModel):
    status: MonthStatus | None = None
    note: str | None = None


class MonthlyEngineer(BaseModel):
    engineer_id: str
    user_id: str
    full_name: str | None = None
    months: dict[int, MonthCell]  # 1-12


class MonthlyPlanner(BaseModel):
    year: int
    engineers: list[MonthlyEngineer]
    totals: dict[int, dict[MonthStatus, int]]

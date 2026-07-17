from datetime import datetime
from zoneinfo import ZoneInfo

from config import DISPLAY_TIMEZONE

_TZ = ZoneInfo(DISPLAY_TIMEZONE)


def format_kickoff(iso_str: str) -> str:
    """Convert a UTC ISO timestamp (as stored by odds_fetcher) to a
    human-readable Nigeria-time (WAT) kickoff string."""
    if not iso_str:
        return "time TBD"
    dt = datetime.fromisoformat(iso_str)
    local = dt.astimezone(_TZ)
    return local.strftime("%a %d %b, %I:%M %p WAT")

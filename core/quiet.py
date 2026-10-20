from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def active(settings, moment=None):
    if not settings.quiet_enabled:
        return False
    local = (moment or datetime.now(timezone.utc)).astimezone(ZoneInfo(settings.background_timezone))
    clock = local.strftime("%H:%M")
    start, end = settings.quiet_start, settings.quiet_end
    # Equal endpoints explicitly mean all day, never a hidden zero-length gap.
    return start <= clock < end if start < end else clock >= start or clock < end


def database_active(db, moment):
    from .config import Settings
    row = db.execute("SELECT value FROM config WHERE id=1").fetchone()
    return active(Settings.model_validate_json(row[0]) if row else Settings(), moment)

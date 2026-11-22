"""Bounded cloud speech failures without response bodies or account data."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math


def retry_seconds(value, default=30):
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try: seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError): seconds = default
    return math.ceil(min(86400, max(0, seconds))) if math.isfinite(seconds) else default


class SpeechUnavailable(ValueError):
    def __init__(self, message, retry_after):
        super().__init__(message)
        self.retry_after = retry_seconds(retry_after)

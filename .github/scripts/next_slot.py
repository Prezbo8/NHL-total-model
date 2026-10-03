"""Seconds until the next run slot: 11:17 AM, 1:17, 3:17, 5:17, 7:17, 9:17 PM Eastern (DST-aware)."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SLOTS = [(11, 17), (13, 17), (15, 17), (17, 17), (19, 17), (21, 17)]

now = datetime.now(ET)
candidates = [(now + timedelta(days=d)).replace(hour=h, minute=mi, second=0, microsecond=0)
              for d in (0, 1) for h, mi in SLOTS]
nxt = min(c for c in candidates if c > now + timedelta(seconds=30))
print(int((nxt - now).total_seconds()), nxt.strftime("%a %-I:%M %p %Z"))

"""Seconds until the next run slot: every hour at :17 from 11:17 AM to 9:17 PM Eastern (DST-aware)."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SLOTS = [(h, 17) for h in range(11, 22)]  # 11:17 AM ... 9:17 PM

now = datetime.now(ET)
candidates = [(now + timedelta(days=d)).replace(hour=h, minute=mi, second=0, microsecond=0)
              for d in (0, 1) for h, mi in SLOTS]
nxt = min(c for c in candidates if c > now + timedelta(seconds=30))
print(int((nxt - now).total_seconds()), nxt.strftime("%a %-I:%M %p %Z"))

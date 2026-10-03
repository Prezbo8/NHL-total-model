"""Seconds until the next run slot (DST-aware), printed as "<seconds> <label>":
every hour at :17 from 11:17 AM to 10:17 PM Eastern, plus 15 minutes before each game's start
(from the NHL schedule; if it can't be read, the hourly slots alone are used)."""
import json
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SLOTS = [(h, 17) for h in range(11, 23)]  # 11:17 AM ... 10:17 PM
PREGAME = timedelta(minutes=15)
MERGE = timedelta(minutes=5)  # a pre-game slot this close to another slot is dropped (no back-to-back runs)


def pregame_slots(now):
    url = f"https://api-web.nhle.com/v1/schedule/{now:%Y-%m-%d}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as f:
        weeks = json.load(f)["gameWeek"]
    starts = {datetime.fromisoformat(g["startTimeUTC"].replace("Z", "+00:00")).astimezone(ET)
              for wk in weeks for g in wk["games"] if g.get("gameState") in ("FUT", "PRE")}
    return [s - PREGAME for s in starts]


now = datetime.now(ET)
slots = [(now + timedelta(days=d)).replace(hour=h, minute=mi, second=0, microsecond=0)
         for d in (0, 1) for h, mi in SLOTS]
labels = {}
try:
    for p in sorted(pregame_slots(now)):
        p = p.replace(second=0, microsecond=0)
        if all(abs(p - s) > MERGE for s in slots):
            slots.append(p)
            labels[p] = " (15 min before puck drop)"
except Exception as e:
    labels["error"] = f" (schedule unavailable: {type(e).__name__}; hourly slots only)"
nxt = min(c for c in slots if c > now + timedelta(seconds=30))
print(int((nxt - now).total_seconds()), nxt.strftime("%a %-I:%M %p %Z") + labels.get(nxt, "") + labels.get("error", ""))

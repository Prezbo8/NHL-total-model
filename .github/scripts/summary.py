"""The last step of every workflow job: what the job is for, what it did and how it ended, in the log and on the run's page
on the Actions tab (GitHub's job summary, under the job diagram).

  python3 .github/scripts/summary.py "<what this job does>"

What it did: the lines the job's steps added to $RUN_SUMMARY (note() in src/health.py, `echo ... >> "$RUN_SUMMARY"`
in shell steps). How it ended: $JOB_STATUS (${{ job.status }}) and any step with an id that failed ($STEPS =
${{ toJSON(steps) }}). What started it: $STARTED_BY (a trigger name below), else GitHub's event + who started it.
"""
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

STARTED = {
    "hourly": "the keeper (hourly slot)",
    "pregame": "the keeper (15 minutes before a game)",
    "morning": "the keeper (8:00 AM slot)",
    "newer": "a model run (MoneyPuck had newer data than the saved copy)",
    "stats": "the once-a-day stats run (it brought in new data)",
    "retry": "the previous model run (a data source or a step failed)",
    "handoff": "the previous keeper's hand-off (or a model run restarting the keeper)",
    "monthly": "a model run (this month's report wasn't saved yet)",
    "schedule": "GitHub's schedule",
    "push": "a code push",
}


def started_by(env):
    trigger = env.get("STARTED_BY") or env.get("GITHUB_EVENT_NAME", "")
    if trigger in STARTED:
        return STARTED[trigger]
    if trigger in ("manual", "workflow_dispatch"):
        actor = env.get("GITHUB_TRIGGERING_ACTOR") or env.get("GITHUB_ACTOR") or ""
        return "another workflow" if actor.endswith("[bot]") else f"a manual run ({actor or 'Run workflow button'})"
    return trigger or "unknown"


def summary(job, env):
    """(text for the log, markdown for the run's page)."""
    path = env.get("RUN_SUMMARY")
    done = [l.rstrip() for l in open(path, encoding="utf-8") if l.strip()] if path and os.path.exists(path) else []
    bad = [k.replace("-", " ") + {"failure": "" if s.get("conclusion") == "failure" else " (ignored)",
                                  "cancelled": " (cancelled)"}[s.get("outcome")]
           for k, s in json.loads(env.get("STEPS") or "{}").items() if s.get("outcome") in ("failure", "cancelled")]
    status = env.get("JOB_STATUS", "")
    if status == "success":
        result = "⚠ FINISHED, WITH PROBLEMS (the ✗ lines)" if any(l.startswith("✗") for l in done) else "✓ SUCCESS"
    elif status == "cancelled":
        result = "✗ CANCELLED (stopped before it finished)"
    else:
        result = "✗ FAILED" + ("" if bad else " (see the step marked ✗ in this job's step list)")
    at = datetime.now(ZoneInfo("America/New_York")).strftime("%a, %b %-d %-I:%M %p %Z")
    by = started_by(env)
    log = ["━" * 72, f"Job:        {job}", f"Started by: {by}", "Done:"]
    log += [f"  {l}" for l in done] or ["  (nothing recorded)"]
    log += [f"Failed step: {', '.join(bad)}"] if bad else []
    log += [f"Result:     {result} ({at})", "━" * 72]
    md = [f"### {result}", "", f"**Job:** {job}  ", f"**Started by:** {by}", ""]
    md += [f"- {l}" for l in done] or ["- (nothing recorded)"]
    md += ["", f"**Failed step:** {', '.join(bad)}"] if bad else []
    md += ["", f"_Finished {at}_", ""]
    return "\n".join(log), "\n".join(md)


if __name__ == "__main__":
    text, md = summary(sys.argv[1], os.environ)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md + "\n")

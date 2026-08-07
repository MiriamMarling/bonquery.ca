"""
Recover historical City-table audit outcomes from retained GitHub Actions logs.

The live audit writes exact results to data/city_audit_history.json. This
backfill recovers older date-level status and mismatch counts from workflow logs
created before the append-only history existed. It records the public run URL
for the full evidence table and never treats a missing or unparseable log as a
passing audit.

Usage:
    python3 scripts/backfill_audit_history_from_actions.py \
        --created 2026-05-27..2026-08-07

Requires the GitHub CLI (`gh`) with read access to this repository.

"""

# Author:  Miriam Marling <miriam@BonQuery.ca>

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORY_FILE = REPO_ROOT / "data" / "city_audit_history.json"
HEADING_RE = re.compile(r"City vs BonQuery Audit.*?(\d{4}-\d{2}-\d{2})")
STATUS_RE = re.compile(r"Status:\*\*.*?(\d+) mismatch\(es\)")


def gh(*args):
    """Run a read-only GitHub CLI command and return standard output."""
    result = subprocess.run(
        ["gh", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def candidate_runs(created):
    """Return successful scheduled runs likely to have changed repository state."""
    raw = gh(
        "run", "list",
        "--workflow", "refresh-daily-occupancy.yml",
        "--created", created,
        "--limit", "1000",
        "--json", "databaseId,createdAt,conclusion,event,headSha,url",
    )
    runs = [
        run for run in json.loads(raw)
        if run["conclusion"] == "success" and run["event"] == "schedule"
    ]
    runs.sort(key=lambda run: run["createdAt"])
    return [
        run for index, run in enumerate(runs)
        if index == len(runs) - 1
        or run["headSha"] != runs[index + 1]["headSha"]
    ]


def parse_run(run):
    """Return date-level failing observations found in one workflow log."""
    try:
        log = gh("run", "view", str(run["databaseId"]), "--log")
    except subprocess.CalledProcessError as exc:
        return [], f"run {run['databaseId']}: {exc.stderr.strip()}"

    observations = {}
    current_date = None
    for line in log.splitlines():
        heading = HEADING_RE.search(line)
        if heading:
            current_date = heading.group(1)
            continue
        if current_date:
            status = STATUS_RE.search(line)
            if status:
                observations[(current_date, int(status.group(1)))] = {
                    "date": current_date,
                    "mismatch_count": int(status.group(1)),
                    "run_created_at": run["createdAt"],
                    "source_url": run["url"],
                }
                current_date = None
    return list(observations.values()), None


def coverage(history):
    exact = {record["date"]: record for record in history.get("records", [])}
    retrospective = {
        date
        for group in history.get("retrospective_evidence", [])
        for date in group.get("dates", [])
    }
    parsed = set(exact) | retrospective
    failed = retrospective | {
        date for date, record in exact.items() if record.get("status") == "fail"
    }
    return {
        "first_audit_date": min(parsed) if parsed else None,
        "last_audit_date": max(parsed) if parsed else None,
        "successfully_parsed_dates": len(parsed),
        "dates_with_mismatches": len(failed),
        "exact_detail_records": len(exact),
        "parser_failures_counted_as_passes": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--created", default="2026-05-27..2026-08-07")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    if not HISTORY_FILE.exists():
        raise SystemExit(f"Missing {HISTORY_FILE}")
    history = json.loads(HISTORY_FILE.read_text())
    exact_dates = {record["date"] for record in history.get("records", [])}

    runs = candidate_runs(args.created)
    observations = []
    warnings = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(parse_run, run): run for run in runs}
        for future in as_completed(futures):
            found, warning = future.result()
            observations.extend(found)
            if warning:
                warnings.append(warning)

    latest_by_date = {}
    for observation in observations:
        prior = latest_by_date.get(observation["date"])
        if prior is None or observation["run_created_at"] > prior["run_created_at"]:
            latest_by_date[observation["date"]] = observation

    action_dates = set(latest_by_date)
    retained_notifications = []
    for group in history.get("retrospective_evidence", []):
        remaining = [
            date for date in group.get("dates", [])
            if date not in action_dates and date not in exact_dates
        ]
        if remaining:
            retained = dict(group)
            retained["dates"] = remaining
            retained_notifications.append(retained)

    action_evidence = [
        {
            "dates": [date],
            "group_mismatch_count": observation["mismatch_count"],
            "evidence_source": "github-actions-log",
            "source_url": observation["source_url"],
            "run_created_at": observation["run_created_at"],
            "details_complete": False,
        }
        for date, observation in sorted(latest_by_date.items())
        if date not in exact_dates
    ]
    history["retrospective_evidence"] = action_evidence + retained_notifications
    history["updated_at"] = datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    history["coverage"] = coverage(history)

    replacement = HISTORY_FILE.with_suffix(".json.next")
    replacement.write_text(json.dumps(history, indent=2) + "\n")
    replacement.replace(HISTORY_FILE)

    print(
        f"Recovered {len(action_dates)} mismatching audit dates from "
        f"{len(runs)} candidate workflow runs."
    )
    print(json.dumps(history["coverage"], indent=2))
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)


if __name__ == "__main__":
    main()

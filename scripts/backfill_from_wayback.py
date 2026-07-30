"""
Backfill City-page scrape data from Wayback Machine snapshots.

Recovers entries for data/city_bridging_triage.json and
data/city_daily_table.json for days where the live scrape failed (e.g. the
2026-07-20 City page redesign that broke the date-heading parser until the
fix landed). Snapshots are fetched from web.archive.org and parsed with the
same extraction functions as the daily scrape (validate_city_page.py), which
understand both the pre- and post-redesign page formats.

Usage:
    python3 scripts/backfill_from_wayback.py --from-ts 20260720 --to-ts 20260731

Notes:
  - Uses the CDX API to enumerate snapshots in the window, dedupes identical
    captures by digest, and fetches the raw page via the `id_` URL flavour
    (original HTML, no Wayback chrome).
  - Wayback rate-limits aggressively (429/503); fetches are spaced out and
    retried with exponential backoff.
  - Later snapshots overwrite earlier ones for the same date, mirroring the
    daily scrape's load-update-write behaviour.
  - Date headings on the City page omit the year; validate_city_page infers
    the current year. A safety pass rewrites the year to the snapshot's own
    year if they differ (only matters when backfilling across New Year).

Author: Miriam Marling <miriam@BonQuery.ca>
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from validate_city_page import (
    CITY_URL,
    extract_bridging_triage,
    extract_city_table_full,
    update_bridging_file,
    update_city_table_file,
)

CDX_URL = "https://web.archive.org/cdx/search/cdx"
SNAPSHOT_URL = "https://web.archive.org/web/{ts}id_/" + CITY_URL

HEADERS = {"User-Agent": "bonquery-backfill/1.0 (miriam@bonquery.ca)"}

FETCH_SPACING_S = 4      # pause between snapshot fetches
MAX_RETRIES     = 5
BACKOFF_BASE_S  = 15     # 15s, 30s, 60s, 120s, 240s


def get_with_retry(url, params=None, timeout=60):
    """GET with exponential backoff on 429/5xx/timeouts. Returns Response
    or None if all retries were exhausted."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=timeout,
                                headers=HEADERS)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (404,):
                print(f"  {url} -> {resp.status_code} (giving up)")
                return None
            print(f"  {url} -> {resp.status_code}")
        except requests.RequestException as exc:
            print(f"  {url} -> {type(exc).__name__}: {exc}")
        if attempt < MAX_RETRIES - 1:
            wait = BACKOFF_BASE_S * (2 ** attempt)
            print(f"  retrying in {wait}s ({attempt + 2}/{MAX_RETRIES})")
            time.sleep(wait)
    return None


def list_snapshots(from_ts, to_ts):
    """Return [(timestamp, digest), ...] for 200-status captures in the
    window, deduped by digest (identical page content -> one fetch)."""
    resp = get_with_retry(CDX_URL, params={
        "url": CITY_URL,
        "from": from_ts,
        "to": to_ts,
        "output": "json",
        "fl": "timestamp,statuscode,digest",
    })
    if resp is None:
        print("CDX API unreachable after retries.", file=sys.stderr)
        return []
    try:
        rows = resp.json()
    except ValueError:
        print(f"CDX returned non-JSON: {resp.text[:200]}", file=sys.stderr)
        return []
    if not rows or len(rows) < 2:
        return []

    seen_digests = set()
    snapshots = []
    for ts, status, digest in rows[1:]:  # rows[0] is the header
        if status != "200" or digest in seen_digests:
            continue
        seen_digests.add(digest)
        snapshots.append((ts, digest))
    return snapshots


def fix_year(entries, snapshot_ts):
    """Rewrite the year in date keys to the snapshot's own year when the
    current-year inference in parse_date_str would be wrong."""
    snap_year = snapshot_ts[:4]
    now_year = str(datetime.now(timezone.utc).year)
    if snap_year == now_year:
        return entries
    fixed = {}
    for date_str, val in entries.items():
        fixed_date = snap_year + date_str[4:]
        print(f"  year fix: {date_str} -> {fixed_date} (snapshot {snapshot_ts})")
        fixed[fixed_date] = val
    return fixed


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--from-ts", required=True,
                    help="CDX window start, YYYYMMDD[hhmmss]")
    ap.add_argument("--to-ts", required=True,
                    help="CDX window end, YYYYMMDD[hhmmss]")
    args = ap.parse_args()

    print(f"Listing Wayback snapshots {args.from_ts}..{args.to_ts} ...")
    snapshots = list_snapshots(args.from_ts, args.to_ts)
    print(f"{len(snapshots)} unique snapshot(s) found.")
    if not snapshots:
        sys.exit(1)

    all_bt = {}      # date -> {...}; later snapshots overwrite
    all_table = {}   # date -> [rows]

    for i, (ts, digest) in enumerate(snapshots):
        print(f"[{i + 1}/{len(snapshots)}] snapshot {ts} ({digest[:8]})")
        resp = get_with_retry(SNAPSHOT_URL.format(ts=ts))
        if resp is None:
            print("  skipped (unreachable)")
            continue
        soup = BeautifulSoup(resp.text, "html.parser")

        bt = fix_year(extract_bridging_triage(soup), ts)
        table = fix_year(extract_city_table_full(soup), ts)
        print(f"  B&T dates: {sorted(bt) or '(none)'} | "
              f"table dates: {sorted(table) or '(none)'}")
        all_bt.update(bt)
        all_table.update(table)

        if i < len(snapshots) - 1:
            time.sleep(FETCH_SPACING_S)

    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print()
    if all_bt:
        update_bridging_file(all_bt, checked_at)
    else:
        print("No Bridging & Triage entries recovered.")
    if all_table:
        update_city_table_file(all_table)
    else:
        print("No full-table entries recovered.")

    print(f"\nRecovered dates: {sorted(set(all_bt) | set(all_table)) or '(none)'}")


if __name__ == "__main__":
    main()

import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CITY_URL = "https://www.toronto.ca/city-government/data-research-maps/research-reports/housing-and-homelessness-research-and-reports/shelter-census/"

DATA_DIR          = Path(__file__).parent.parent / "data"
OCCUPANCY_FILE    = DATA_DIR / "daily_occupancy.json"
OUTPUT_FILE       = DATA_DIR / "city_validation.json"
BRIDGING_FILE     = DATA_DIR / "city_bridging_triage.json"
CITY_TABLE_FILE   = DATA_DIR / "city_daily_table.json"
HEALTH_FILE       = DATA_DIR / "scrape_health.json"
FAILURE_SOURCE_FILE = DATA_DIR / "city_page_parser_failure.html"

# Maps exact City table label text → BonQuery key.
# Only rows where the City label is stable and maps cleanly to a BonQuery key.
# The City redesigned the page ~2026-07-20 ("Shelter Census" → "Daily Shelter
# & Overnight Service Usage"); legacy labels are kept so Wayback Machine
# snapshots of the pre-redesign page still parse (see backfill_from_wayback.py).
LABEL_TO_KEY = {
    "All Shelter Programs, Total":            "all_shelter",
    "Shelter Programs, Room-Based, Total":    "room_based",
    "Singles Sector Programs, Total":         "singles_sector",
    "Shelter Programs, Singles, Total":       "singles_shelter_total",
    "Family Sector, Total":                   "fam_total",
    "Families, Emergency Shelter Programs":   "fam_emerg",
    "Families, Transitional Shelter Programs":"fam_trans_r",
    "Families, Motel/Hotel Programs":         "fam_hotel",
    "Single Sector Motel/Hotel, Total":       "sng_hotel",
    "Singles Sectors, Total":                 "singles_total",
    "Emergency Shelter Programs, Total":      "emerg_total",
    "Mixed Adult, Emergency":                 "mix_emerg",
    "Men, Emergency":                         "men_emerg",
    "Women, Emergency":                       "wom_emerg",
    "Youth, Emergency":                       "yth_emerg",
    "Transitional Shelter Programs, Total":   "trans_total",
    "Mixed Adult, Transitional":              "mix_trans",
    "Families, Transitional":                 "fam_trans_b",
    "Men, Transitional":                      "men_trans",
    "Women, Transitional":                    "wom_trans",
    "Youth, Transitional":                    "yth_trans",
    "Allied Services, Total":                 "allied_total",
    "24-Hour Respites":                       "respites",
    "24-Hour Women's Drop-ins":               "dropin",
    "24-Hour Temporary Response Sites":       "temp_resp",
    "Hotels":                                 "hotels",
    "Isolation/Recovery Programs Combined Total": "iso",  # legacy (pre-2026-07-20)
    "Temporary Isolation/Recovery Programs": "iso",
    "Temporary Isolation/Recovery Programs Combined Total": "iso",
    "Temporary Programs, Total":                 "temp_summ",
}

MONTH_NAMES = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11,
    "Dec": 12,
    # "Sept" is the City's own house style in some months and is not the
    # three-letter abbreviation, so it needs its own entry.
    "Sept": 9,
}

# Lookup is done on a normalised key (lowercased, trailing period stripped) so
# a single spelling change on the City's side cannot cost us a day of data.
# The City has already changed this heading format once without notice: it
# moved from "August 6" to "Aug 7" mid-scrape in August 2026.
MONTH_LOOKUP = {name.lower(): num for name, num in MONTH_NAMES.items()}

# section / col_type metadata for every key in LABEL_TO_KEY.
# Derived from data/city_reference_2026-05-14.json; used by
# extract_city_table_full() to keep output schema stable across scrapes.
KEY_META = {
    "all_shelter":    {"section": "summary",       "col_type": "summary"},
    "room_based":     {"section": "summary",       "col_type": "summary"},
    "singles_sector": {"section": "summary",       "col_type": "summary"},
    "singles_shelter_total": {"section": "summary", "col_type": "summary"},
    "fam_total":      {"section": "room_based",    "col_type": "room"},
    "fam_emerg":      {"section": "room_based",    "col_type": "room"},
    "fam_trans_r":    {"section": "room_based",    "col_type": "room"},
    "fam_hotel":      {"section": "room_based",    "col_type": "room"},
    "sng_hotel":      {"section": "room_based",    "col_type": "room"},
    "singles_total":  {"section": "bed_based",     "col_type": "bed"},
    "emerg_total":    {"section": "bed_based",     "col_type": "bed"},
    "mix_emerg":      {"section": "bed_based",     "col_type": "bed"},
    "men_emerg":      {"section": "bed_based",     "col_type": "bed"},
    "wom_emerg":      {"section": "bed_based",     "col_type": "bed"},
    "yth_emerg":      {"section": "bed_based",     "col_type": "bed"},
    "trans_total":    {"section": "bed_based",     "col_type": "bed"},
    "mix_trans":      {"section": "bed_based",     "col_type": "bed"},
    "fam_trans_b":    {"section": "bed_based",     "col_type": "bed"},
    "men_trans":      {"section": "bed_based",     "col_type": "bed"},
    "wom_trans":      {"section": "bed_based",     "col_type": "bed"},
    "yth_trans":      {"section": "bed_based",     "col_type": "bed"},
    "allied_total":   {"section": "allied",        "col_type": "bed"},
    "respites":       {"section": "allied",        "col_type": "bed"},
    "dropin":         {"section": "allied",        "col_type": "bed"},
    "temp_resp":      {"section": "temp_bed",      "col_type": "bed"},
    "hotels":         {"section": "temp_room",     "col_type": "room"},
    "iso":            {"section": "iso_recovery",  "col_type": "room"},
    "temp_summ":      {"section": "temp_summary",  "col_type": "summary"},
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}

# Matches the daily-table heading in both page generations:
#   pre-2026-07-20:  "Daily Occupancy & Capacity for July 18"
#   post-redesign:   "Daily Shelter & Overnight Service Usage for July 28"
#     (heading now lives on an accordion toggle <div>; the walk-based section
#      detection below is tag-agnostic, so only the text pattern matters)
#   from 2026-08-07:  "Daily Shelter & Overnight Service Usage for Aug 7"
#
# Deliberately permissive about the parts the City has shown it will change
# without notice, while still requiring the distinctive heading wording:
#   - "&", "&amp;", or the spelled-out "and"
#   - full or abbreviated month, with or without a trailing period
#   - any capitalisation
#   - an optional trailing year ("August 7, 2026"), which is preferred over
#     inferring the year when the City supplies it
_AMP = r"(?:&(?:amp;)?|and)"
DATE_PAT = re.compile(
    r"Daily\s+(?:Occupancy\s*" + _AMP + r"\s*Capacity"
    r"|Shelter\s*" + _AMP + r"\s*Overnight\s+Service\s+Usage)"
    r"\s+for\s+([A-Za-z]+)\.?\s+(\d{1,2})"
    r"(?:\s*,?\s*(\d{4}))?",
    re.IGNORECASE,
)


def get_bonquery_latest_date():
    """Return the most recent date string in daily_occupancy.json, or None."""
    try:
        daily_occ = json.loads(OCCUPANCY_FILE.read_text())
        dates = sorted({r["date"] for r in daily_occ if r.get("date")}, reverse=True)
        return dates[0] if dates else None
    except Exception:
        return None


def write_result(city_reachable, passed, city_date, bonquery_latest_date, mismatches):
    result = {
        "city_date": city_date,
        "bonquery_latest_date": bonquery_latest_date,
        "city_reachable": city_reachable,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "passed": passed,
        "mismatches": mismatches,
    }
    OUTPUT_FILE.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


def parse_number(text):
    cleaned = re.sub(r"[,\s]", "", text.strip())
    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_rate(text):
    """Parse a percentage string like '95.5%' or '95.5' → float, or None."""
    cleaned = re.sub(r"[%\s,]", "", text.strip())
    if not cleaned or cleaned in ("—", "-", "N/A", "n/a"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_date_str(month_str, day_str, year_str=None):
    """Convert 'May', '26' → '2026-05-26'. Returns None if unrecognised.

    Accepts 'May', 'may', 'Sept', 'Sept.' and friends. When the City supplies
    a year in the heading it is used verbatim; otherwise the year is inferred.

    Inference is not simply "the current year". A catch-up table for Dec 31
    read on Jan 2 would then be stamped a year in the future and sort to the
    end of the archive forever. Any date landing more than a few days ahead of
    today is therefore treated as belonging to the previous year.
    """
    if not month_str:
        return None
    month = MONTH_LOOKUP.get(month_str.strip().rstrip(".").lower())
    if not month:
        return None

    day = int(day_str)
    today = datetime.now(timezone.utc).date()

    if year_str:
        year = int(year_str)
    else:
        year = today.year
        try:
            if date(year, month, day) > today + timedelta(days=3):
                year -= 1
        except ValueError:
            return None      # e.g. Feb 30 — not a real date

    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def write_scrape_health(fetch_ok, soup, bt_entries, table_entries, city_date,
                        page_html=None):
    """Write data/scrape_health.json — the scrape's self-diagnosis.

    Distinguishes "the City published nothing" from "the City published a
    table this parser can no longer read", so CI can alert on day 1 of a
    page-format change instead of failing silently (cf. the 2026-07-20
    redesign, which went unnoticed for 9 days).

    scrape_broken is the alert condition: the page was fetched, something
    table-shaped is present on it, yet the parser extracted no usable data
    (no date heading, no mapped rows, or no B&T entry).
    """
    if soup is not None:
        td_count = len(soup.find_all("td"))
        page_text = soup.get_text(" ", strip=True)
        known_labels_seen = sum(1 for lbl in LABEL_TO_KEY if lbl in page_text)
        table_detected = td_count >= 20 or known_labels_seen >= 3
    else:
        td_count = 0
        known_labels_seen = 0
        table_detected = False

    parser_ok = bool(city_date) and bool(table_entries) and bool(bt_entries)
    health = {
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetch_ok": fetch_ok,
        "table_detected": table_detected,
        "td_cell_count": td_count,
        "known_labels_seen": known_labels_seen,
        "date_heading_found": bool(city_date),
        "bt_dates_extracted": sorted(bt_entries),
        "table_dates_extracted": sorted(table_entries),
        "rows_extracted": sum(len(v) for v in table_entries.values()),
        "parser_ok": parser_ok,
        "scrape_broken": fetch_ok and table_detected and not parser_ok,
    }
    if health["scrape_broken"] and page_html is not None:
        FAILURE_SOURCE_FILE.write_text(page_html, encoding="utf-8")
        health["failure_source_file"] = FAILURE_SOURCE_FILE.name
        health["failure_source_sha256"] = hashlib.sha256(
            page_html.encode("utf-8")
        ).hexdigest()
    HEALTH_FILE.write_text(json.dumps(health, indent=2))
    print(f"scrape_health.json: parser_ok={parser_ok}, "
          f"table_detected={table_detected}, "
          f"scrape_broken={health['scrape_broken']}")


def extract_city_date(soup):
    """Return the FIRST date string found on the page (for validation logic)."""
    for tag in soup.find_all(True):
        m = DATE_PAT.search(tag.get_text(strip=True))
        if m:
            return parse_date_str(m.group(1), m.group(2), m.group(3))
    return None


def extract_city_values(soup):
    """Return {key: individuals_int} for all rows matching LABEL_TO_KEY."""
    city_values = {}
    for td in soup.find_all("td"):
        label = td.get_text(strip=True)
        if label in LABEL_TO_KEY:
            key = LABEL_TO_KEY[label]
            row = td.find_parent("tr")
            if not row:
                continue
            cells = row.find_all("td")
            if len(cells) >= 2:
                val = parse_number(cells[1].get_text(strip=True))
                if val is not None and key not in city_values:
                    city_values[key] = val
    return city_values


def _row_individual(td):
    """Given a <td> label cell, return the integer value in the next cell."""
    row = td.find_parent("tr")
    if not row:
        return None
    cells = row.find_all("td")
    if len(cells) >= 2:
        return parse_number(cells[1].get_text(strip=True))
    return None


def extract_bridging_triage(soup):
    """Extract Bridging & Triage and Total People Accommodated for every date
    table on the page. The City sometimes publishes multiple tables on one page
    to make up for weekends/holidays.

    Returns a dict keyed by ISO date string:
        {"2026-05-26": {"bridging_triage": 30, "total_people": 7948}, ...}

    Only entries where at least bridging_triage was found are included.
    """
    results = {}

    # Walk every element in document order, tracking the current date section.
    # A new date section begins whenever we hit a tag whose text matches
    # DATE_PAT.  Within each section, the first "Bridging & Triage Programs"
    # and "Total People Accommodated" <td> cells give the values.
    current_date = None
    bt_val = None
    tp_val = None

    def flush():
        if current_date and bt_val is not None:
            results[current_date] = {
                "bridging_triage": bt_val,
                "total_people": tp_val,
            }

    for tag in soup.find_all(True):
        text = tag.get_text(strip=True)

        # Check if this tag opens a new date section
        m = DATE_PAT.search(text)
        if m and tag.name not in ("table", "tbody", "tr", "td", "th"):
            new_date = parse_date_str(m.group(1), m.group(2), m.group(3))
            if new_date and new_date != current_date:
                flush()
                current_date = new_date
                bt_val = None
                tp_val = None
            continue

        if tag.name != "td":
            continue

        if bt_val is None and text == "Bridging & Triage Programs":
            bt_val = _row_individual(tag)

        if tp_val is None and text == "Total People Accommodated":
            tp_val = _row_individual(tag)

    flush()
    return results


def update_bridging_file(new_entries, checked_at):
    """Load-update-write city_bridging_triage.json with new_entries.

    File format:
    {
      "note": "...",
      "first_captured": "YYYY-MM-DD",
      "entries": {"YYYY-MM-DD": {"bridging_triage": N, "total_people": N}, ...}
    }
    """
    if BRIDGING_FILE.exists():
        try:
            existing = json.loads(BRIDGING_FILE.read_text())
        except Exception:
            existing = {}
    else:
        existing = {}

    entries = existing.get("entries", {})
    first = existing.get("first_captured")

    for date_str, vals in new_entries.items():
        entries[date_str] = vals
        if first is None or date_str < first:
            first = date_str

    payload = {
        "note": (
            "Bridging & Triage Programs and Total People Accommodated are not "
            "published to the City of Toronto open data (CKAN) export. These "
            "figures are scraped daily from the City's shelter census page "
            "(toronto.ca/shelter-census) when the City posts them. Data is "
            f"available from {first} onward. Days where the City did not "
            "publish a table (weekends, holidays) will be absent unless the "
            "City retroactively posts catch-up tables on a subsequent day."
        ),
        "first_captured": first,
        "entries": dict(sorted(entries.items())),
    }
    BRIDGING_FILE.write_text(json.dumps(payload, indent=2))
    print(f"city_bridging_triage.json: {len(new_entries)} new entries "
          f"({', '.join(sorted(new_entries))}); total={len(entries)}")
    return entries


def extract_city_table_full(soup):
    """Extract all columns from the City table for every date section on the page.

    Follows the same document-order walk as extract_bridging_triage so it
    handles pages with multiple date tables (weekend catch-ups).

    City table column order: label | individuals | occupied | unoccupied |
    actual capacity | occupancy rate.  Summary rows (e.g. "All Shelter
    Programs, Total") typically omit occ/unocc/cap/rate — parse_number /
    parse_rate will return None for those cells.

    Returns a dict keyed by ISO date string:
        {"2026-05-28": [
            {"key": "...", "label": "...", "section": "...",
             "col_type": "...", "city_ind": N, "city_occ": N|None,
             "city_unocc": N|None, "city_cap": N|None,
             "city_rate": F|None},
            ...
        ]}
    """
    results = {}
    current_date = None
    current_rows = []
    # key → index into current_rows. A dict rather than a set because the City
    # prints several labels twice per date: once in the summary block with only
    # an individuals count, and again in its own section with the full columns.
    # Keeping the first occurrence would silently discard occupied, unoccupied,
    # capacity and rate for those rows (e.g. "Allied Services, Total").
    seen_keys: dict = {}

    VALUE_FIELDS = ("city_ind", "city_occ", "city_unocc", "city_cap",
                    "city_rate")

    def richness(row):
        """How many of the numeric columns this row actually carries.

        Also protects against the City's repeated header rows, whose label cell
        matches a real label but whose value cells are words ("Occupied Rooms"),
        so every numeric field parses to None and the score is 0.
        """
        return sum(1 for f in VALUE_FIELDS if row[f] is not None)

    def flush():
        if current_date and current_rows:
            results[current_date] = list(current_rows)

    for tag in soup.find_all(True):
        text = tag.get_text(strip=True)

        m = DATE_PAT.search(text)
        if m and tag.name not in ("table", "tbody", "tr", "td", "th"):
            new_date = parse_date_str(m.group(1), m.group(2), m.group(3))
            if new_date and new_date != current_date:
                flush()
                current_date = new_date
                current_rows = []
                seen_keys = {}
            continue

        if tag.name != "td":
            continue

        label = text
        if label not in LABEL_TO_KEY:
            continue

        key = LABEL_TO_KEY[label]

        row = tag.find_parent("tr")
        if not row:
            continue
        cells = row.find_all("td")

        def cell_text(idx):
            return cells[idx].get_text(strip=True) if len(cells) > idx else ""

        meta = KEY_META.get(key, {"section": "unknown", "col_type": "unknown"})
        new_row = {
            "key":        key,
            "label":      label,
            "section":    meta["section"],
            "col_type":   meta["col_type"],
            "city_ind":   parse_number(cell_text(1)),
            "city_occ":   parse_number(cell_text(2)),
            "city_unocc": parse_number(cell_text(3)),
            "city_cap":   parse_number(cell_text(4)),
            "city_rate":  parse_rate(cell_text(5)),
        }

        if key not in seen_keys:
            seen_keys[key] = len(current_rows)
            current_rows.append(new_row)
        elif richness(new_row) > richness(current_rows[seen_keys[key]]):
            # Upgrade in place: a later, fuller occurrence replaces the values
            # but keeps the row's original position, so the archive's row order
            # stays stable across scrapes.
            current_rows[seen_keys[key]] = new_row

    flush()
    return results


def update_city_table_file(new_entries):
    """Accumulate full-table scrapes into a single city_daily_table.json.

    File format mirrors city_bridging_triage.json:
    {
      "note": "...",
      "first_captured": "YYYY-MM-DD",
      "entries": {"YYYY-MM-DD": [array of row dicts], ...}
    }
    New dates are added; existing dates are overwritten with fresh values.
    """
    if CITY_TABLE_FILE.exists():
        try:
            existing = json.loads(CITY_TABLE_FILE.read_text())
        except Exception:
            existing = {}
    else:
        existing = {}

    entries = existing.get("entries", {})
    first = existing.get("first_captured")

    for date_str, rows in new_entries.items():
        entries[date_str] = rows
        if first is None or date_str < first:
            first = date_str

    payload = {
        "note": (
            "Full City of Toronto shelter census table scraped daily from "
            "toronto.ca/shelter-census. Each entry is an array of rows keyed "
            "by BonQuery sector key, matching the schema of "
            "city_reference_2026-05-14.json (key, label, section, col_type, "
            "city_ind, city_occ, city_unocc, city_cap, city_rate). Available "
            f"from {first} onward. Days where the City did not publish a table "
            "(weekends, holidays) will be absent unless the City retroactively "
            "posts catch-up tables on a subsequent day."
        ),
        "first_captured": first,
        "last_scraped": sorted(new_entries),
        "entries": dict(sorted(entries.items())),
    }
    CITY_TABLE_FILE.write_text(json.dumps(payload, indent=2))
    print(
        f"city_daily_table.json: {len(new_entries)} new date(s) "
        f"({', '.join(sorted(new_entries))}); total={len(entries)}"
    )


def main():
    bonquery_latest_date = get_bonquery_latest_date()

    # ── Fetch City page ───────────────────────────────────────────────────────
    try:
        resp = requests.get(CITY_URL, timeout=30, headers=HEADERS)
        resp.raise_for_status()
    except Exception as exc:
        write_scrape_health(False, None, {}, {}, None)
        write_result(
            city_reachable=False,
            passed=False,
            city_date=None,
            bonquery_latest_date=bonquery_latest_date,
            mismatches=[{"label": "City page fetch failed", "key": None,
                         "city": None, "bonquery": str(exc)}],
        )
        sys.exit(0)

    soup = BeautifulSoup(resp.text, "html.parser")

    # ── Bridging & Triage — capture for every date table on the page ─────────
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    bt_entries = extract_bridging_triage(soup)
    if bt_entries:
        update_bridging_file(bt_entries, checked_at)
    else:
        print("city_bridging_triage.json: no B&T rows found on page today")

    # ── Full table snapshot — all columns for every date section ─────────────
    table_entries = extract_city_table_full(soup)
    if table_entries:
        update_city_table_file(table_entries)
    else:
        print("city_daily_table.json: no table rows found on page today")

    # ── Parse primary date heading (for validation) ───────────────────────────
    city_date = extract_city_date(soup)

    # ── Scrape self-diagnosis — always written, whatever happens below ───────
    write_scrape_health(True, soup, bt_entries, table_entries, city_date,
                        resp.text)

    if not city_date:
        write_result(
            city_reachable=False,
            passed=False,
            city_date=None,
            bonquery_latest_date=bonquery_latest_date,
            mismatches=[{"label": "City page date not found", "key": None,
                         "city": None, "bonquery": "Could not parse date heading"}],
        )
        sys.exit(0)

    # ── Page is reachable from here on; errors are value mismatches ──────────

    city_values = extract_city_values(soup)
    if not city_values:
        write_result(
            city_reachable=True,
            passed=False,
            city_date=city_date,
            bonquery_latest_date=bonquery_latest_date,
            mismatches=[{"label": "City table parse failed", "key": None,
                         "city": None, "bonquery": "No table rows matched expected labels"}],
        )
        sys.exit(0)

    try:
        daily_occ = json.loads(OCCUPANCY_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        write_result(
            city_reachable=True,
            passed=False,
            city_date=city_date,
            bonquery_latest_date=bonquery_latest_date,
            mismatches=[{"label": "BonQuery occupancy data unavailable", "key": None,
                         "city": None, "bonquery": str(exc)}],
        )
        sys.exit(0)
    bonquery_rows = {r["key"]: r for r in daily_occ if r["date"] == city_date}

    if not bonquery_rows:
        write_result(
            city_reachable=True,
            passed=False,
            city_date=city_date,
            bonquery_latest_date=bonquery_latest_date,
            mismatches=[{"label": "No BonQuery data for City date", "key": None,
                         "city": None,
                         "bonquery": f"No rows found for {city_date}"}],
        )
        sys.exit(0)

    mismatches = []
    for label, key in LABEL_TO_KEY.items():
        city_val = city_values.get(key)
        bq_row = bonquery_rows.get(key)
        if city_val is None or bq_row is None:
            continue
        bq_val = bq_row.get("ind")
        if bq_val is None:
            continue
        if city_val != bq_val:
            mismatches.append({"label": label, "key": key,
                               "city": city_val, "bonquery": bq_val})

    write_result(
        city_reachable=True,
        passed=len(mismatches) == 0,
        city_date=city_date,
        bonquery_latest_date=bonquery_latest_date,
        mismatches=mismatches,
    )


if __name__ == "__main__":
    main()

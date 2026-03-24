"""Extract contributor data from MediaWiki database (DDEV MariaDB).

One-time script. Requires DDEV running with the imported ayurwiki.sql.gz.

Usage:
    ddev start
    ddev import-db --file=ayurwiki.sql.gz   # if not already imported
    python3 scripts/extract_contributors.py
"""

import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
PAGE_LOCATIONS = os.path.join(ROOT_DIR, "page_locations.json")
OUTPUT = os.path.join(ROOT_DIR, "data", "contributors.json")

# Only include users with at least this many edits in namespace 0
MIN_EDITS = 3


def run_query(sql):
    """Run a SQL query via ddev mysql and return rows as list of dicts."""
    result = subprocess.run(
        ["ddev", "mysql", "-e", sql],
        capture_output=True, text=True, cwd=ROOT_DIR
    )
    if result.returncode != 0:
        print(f"MySQL error: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    lines = result.stdout.strip().split("\n")
    if len(lines) < 2:
        return []

    headers = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        values = line.split("\t")
        rows.append(dict(zip(headers, values)))
    return rows


def format_timestamp(ts):
    """Convert MediaWiki timestamp (20180329111830) to date string."""
    try:
        dt = datetime.strptime(ts[:8], "%Y%m%d")
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ts


def main():
    # Load page title -> md path mapping
    with open(PAGE_LOCATIONS, "r", encoding="utf-8") as f:
        page_locations = json.load(f)

    print(f"Loaded {len(page_locations)} page mappings")

    # Query all revisions for namespace 0 pages
    print("Querying revisions (this may take a moment)...")
    rows = run_query("""
        SELECT
            p.page_title,
            a.actor_name,
            COALESCE(u.user_real_name, '') AS user_real_name,
            CASE WHEN a.actor_user > 0 THEN 1 ELSE 0 END AS is_registered,
            r.rev_timestamp,
            COALESCE(r.rev_len, 0) AS rev_len,
            COALESCE(parent.rev_len, 0) AS parent_len,
            COALESCE(c.comment_text, '') AS comment_text
        FROM revision r
        JOIN page p ON r.rev_page = p.page_id
        JOIN actor a ON r.rev_actor = a.actor_id
        LEFT JOIN user u ON a.actor_user = u.user_id AND a.actor_user > 0
        LEFT JOIN revision parent ON r.rev_parent_id = parent.rev_id
        LEFT JOIN comment c ON r.rev_comment_id = c.comment_id
        WHERE p.page_namespace = 0
        ORDER BY p.page_title, r.rev_timestamp
    """)

    print(f"Retrieved {len(rows)} revisions")

    # Build per-page contributor data
    pages = defaultdict(lambda: {"contributors": defaultdict(lambda: {
        "edits": [], "bytes_added": 0, "bytes_removed": 0,
        "first_edit": None, "last_edit": None, "registered": False,
        "real_name": ""
    }), "anonymous": {"edit_count": 0, "bytes_added": 0, "bytes_removed": 0}})

    # Track global user stats
    user_stats = defaultdict(lambda: {
        "real_name": "", "total_edits": 0,
        "total_bytes_added": 0, "total_bytes_removed": 0,
        "pages": set()
    })

    for row in rows:
        page_title = row["page_title"]
        actor = row["actor_name"]
        registered = row["is_registered"] == "1"
        rev_len = int(row["rev_len"])
        parent_len = int(row["parent_len"])
        delta = rev_len - parent_len
        date = format_timestamp(row["rev_timestamp"])
        summary = row["comment_text"]

        # Clean up edit summaries - strip MediaWiki markup
        if summary.startswith("/* ") and " */" in summary:
            section = summary.split("*/")[0].replace("/* ", "").strip()
            rest = summary.split("*/", 1)[1].strip()
            summary = f"Edited {section}" + (f": {rest}" if rest else "")

        # Map to md path
        md_path = page_locations.get(page_title)
        if not md_path:
            continue

        if not registered:
            anon = pages[md_path]["anonymous"]
            anon["edit_count"] += 1
            if delta > 0:
                anon["bytes_added"] += delta
            else:
                anon["bytes_removed"] += abs(delta)
            continue

        # Registered user
        contrib = pages[md_path]["contributors"][actor]
        contrib["registered"] = True
        contrib["real_name"] = row["user_real_name"] or ""

        if delta > 0:
            contrib["bytes_added"] += delta
        else:
            contrib["bytes_removed"] += abs(delta)

        if not contrib["first_edit"]:
            contrib["first_edit"] = date
        contrib["last_edit"] = date

        contrib["edits"].append({
            "date": date,
            "summary": summary[:200] if summary else "",
            "delta": delta
        })

        # Update global stats
        us = user_stats[actor]
        us["real_name"] = row["user_real_name"] or ""
        us["total_edits"] += 1
        if delta > 0:
            us["total_bytes_added"] += delta
        else:
            us["total_bytes_removed"] += abs(delta)
        us["pages"].add(md_path)

    # Convert to serializable format
    output = {"pages": {}, "users": {}}

    for md_path, page_data in pages.items():
        contributors = []
        for name, cdata in page_data["contributors"].items():
            edit_count = len(cdata["edits"])
            if edit_count < MIN_EDITS:
                # Fold small contributors into anonymous
                page_data["anonymous"]["edit_count"] += edit_count
                page_data["anonymous"]["bytes_added"] += cdata["bytes_added"]
                page_data["anonymous"]["bytes_removed"] += cdata["bytes_removed"]
                continue

            contributors.append({
                "name": name,
                "real_name": cdata["real_name"],
                "registered": True,
                "edit_count": edit_count,
                "first_edit": cdata["first_edit"],
                "last_edit": cdata["last_edit"],
                "bytes_added": cdata["bytes_added"],
                "bytes_removed": cdata["bytes_removed"],
                "edits": cdata["edits"]
            })

        # Sort by edit count descending
        contributors.sort(key=lambda c: -c["edit_count"])

        if contributors or page_data["anonymous"]["edit_count"] > 0:
            entry = {"contributors": contributors}
            if page_data["anonymous"]["edit_count"] > 0:
                entry["anonymous"] = page_data["anonymous"]
            output["pages"][md_path] = entry

    # Build users summary
    for name, us in user_stats.items():
        if us["total_edits"] >= MIN_EDITS:
            output["users"][name] = {
                "real_name": us["real_name"],
                "total_edits": us["total_edits"],
                "total_bytes_added": us["total_bytes_added"],
                "total_bytes_removed": us["total_bytes_removed"],
                "pages_count": len(us["pages"])
            }

    # Sort users by total edits
    output["users"] = dict(sorted(
        output["users"].items(),
        key=lambda x: -x[1]["total_edits"]
    ))

    # Write output
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    page_count = len(output["pages"])
    user_count = len(output["users"])
    file_size = os.path.getsize(OUTPUT) / (1024 * 1024)
    print(f"\nDone! Wrote {OUTPUT}")
    print(f"  Pages with contributors: {page_count}")
    print(f"  Named contributors: {user_count}")
    print(f"  File size: {file_size:.1f} MB")


if __name__ == "__main__":
    main()

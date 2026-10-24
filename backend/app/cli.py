"""Command line: unattended scans (Windows Task Scheduler), quick searches, folder management.

    python -m app.cli add-folder "D:\\Telegram books"
    python -m app.cli scan [--force]
    python -m app.cli search "vestibular schwannoma hearing preservation"
    python -m app.cli status
"""
from __future__ import annotations

import argparse
import json
import sys

from .db import init_db, now_iso, session
from .services import indexer, jobs
from .services import search as search_svc
from .services.paths import normalize


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="academy")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add-folder")
    a.add_argument("path")
    s = sub.add_parser("scan")
    s.add_argument("--force", action="store_true", help="re-extract every document")
    q = sub.add_parser("search")
    q.add_argument("query")
    q.add_argument("-n", type=int, default=10)
    sub.add_parser("status")
    args = ap.parse_args(argv)
    init_db()

    if args.cmd == "add-folder":
        p = normalize(args.path)
        with session() as c:
            c.execute("INSERT OR IGNORE INTO folders(path, label, added_at) VALUES (?,?,?)", (p, p, now_iso()))
        print(f"Folder registered: {p}")
    elif args.cmd == "scan":
        job_id = jobs.start("scan", lambda ctx: indexer.run_scan(ctx, None, args.force))
        last = None
        while True:
            j = jobs.wait(job_id, timeout=2)
            pr = j["progress"]
            line = f"{pr.get('phase')}: {pr.get('indexed', 0)}/{pr.get('to_index', '?')} {pr.get('current', '')}"
            if line != last:
                print(line, flush=True)
                last = line
            if j["status"] != "running":
                print(j["log"][-4000:])
                return 0 if j["status"] == "done" else 1
    elif args.cmd == "search":
        with session() as c:
            res = search_svc.search(c, args.query, limit=args.n)
        for h in res["hits"]:
            snip = h["snippet"].replace(search_svc.MARK_OPEN, "[").replace(search_svc.MARK_CLOSE, "]")
            print(f"- {h['citation']['formatted']}\n  {snip[:300]}\n")
        if not res["hits"]:
            print("No supporting passage found in the indexed library.")
    elif args.cmd == "status":
        with session() as c:
            rows = c.execute("SELECT status, COUNT(*) n FROM documents GROUP BY status").fetchall()
            folders = c.execute("SELECT path, last_scan_at FROM folders").fetchall()
        print(json.dumps({"documents": {r["status"]: r["n"] for r in rows},
                          "folders": [dict(f) for f in folders]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

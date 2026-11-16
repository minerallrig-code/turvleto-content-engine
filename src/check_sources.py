#!/usr/bin/env python3
"""Lightweight URL availability check; this does not establish factual truth."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_url(url: str, timeout: int = 12) -> dict:
    if not url.startswith(("https://", "http://")):
        return {"url": url, "reachable": False, "status": "invalid_scheme"}
    request = urllib.request.Request(url, headers={"User-Agent": "TurvletoContentEngine/1.0"}, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"url": url, "reachable": True, "http_status": response.status, "status": "reachable"}
    except urllib.error.HTTPError as exc:
        if exc.code in (405, 403):
            try:
                get_request = urllib.request.Request(url, headers={"User-Agent": "TurvletoContentEngine/1.0"}, method="GET")
                with urllib.request.urlopen(get_request, timeout=timeout) as response:
                    return {"url": url, "reachable": True, "http_status": response.status, "status": "reachable"}
            except Exception as retry_exc:
                return {"url": url, "reachable": False, "status": "check_failed", "error": str(retry_exc)}
        return {"url": url, "reachable": False, "http_status": exc.code, "status": "http_error"}
    except Exception as exc:
        return {"url": url, "reachable": False, "status": "check_failed", "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", help="JSON файл с объектом topics или одной темой")
    args = parser.parse_args()
    path = (ROOT / args.file).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    topics = data.get("topics", []) if isinstance(data, dict) else []
    report = []
    for topic in topics:
        checked = [check_url(source.get("url", "")) for source in topic.get("sources", [])]
        report.append({"title": topic.get("title"), "sources": checked, "fact_check_note": "Доступность URL не подтверждает достоверность содержания."})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Check technical URL reachability and write a review report.

A reachable URL is NOT evidence that its contents support a claim.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def check_url(url: str, timeout: int = 12) -> dict[str, Any]:
    if not isinstance(url, str) or not url.strip():
        return {"url": url or "", "reachable": False, "status": "empty_url"}
    if not url.startswith(("https://", "http://")):
        return {"url": url, "reachable": False, "status": "invalid_scheme"}

    headers = {"User-Agent": "Mozilla/5.0 (compatible; TurvletoContentEngine/1.0)", "Range": "bytes=0-1023"}
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return {
                    "url": url,
                    "reachable": True,
                    "http_status": response.status,
                    "final_url": response.geturl(),
                    "status": "reachable",
                    "method": method,
                }
        except urllib.error.HTTPError as exc:
            if method == "HEAD" or exc.code in (403, 405, 429, 500, 502, 503, 504):
                last_error = {"url": url, "reachable": False, "http_status": exc.code, "status": "http_error"}
                continue
            return {"url": url, "reachable": False, "http_status": exc.code, "status": "http_error"}
        except Exception as exc:
            last_error = {"url": url, "reachable": False, "status": "check_failed", "error": str(exc)[:300]}
            if method == "HEAD":
                continue
    return last_error


def build_report(data: dict[str, Any], timeout: int = 12) -> dict[str, Any]:
    topic_reports = []
    for topic in data.get("topics", []):
        sources = topic.get("sources", [])
        checked = [check_url(source.get("url", ""), timeout) for source in sources]
        if not sources:
            technical_status = "no_sources"
        elif all(item["reachable"] for item in checked):
            technical_status = "all_reachable"
        elif any(item["reachable"] for item in checked):
            technical_status = "partially_reachable"
        else:
            technical_status = "none_reachable"
        topic["source_reachability"] = technical_status
        # Technical availability never upgrades a topic to fact-checked/proposed.
        topic["source_review_status"] = "pending_editorial_review"
        topic_reports.append({
            "title": topic.get("title", ""),
            "topic_status": topic.get("status", "needs_research"),
            "technical_status": technical_status,
            "sources": checked,
            "fact_check_note": "Доступность URL не подтверждает, что страница содержит доказательство для утверждений темы. Нужна ручная проверка содержания."
        })
    return {
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "date": data.get("date"),
        "topics": topic_reports,
        "editorial_approval_required": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", help="JSON-файл с объектом topics")
    parser.add_argument("--report", help="Путь для сохранения отчёта JSON")
    parser.add_argument("--timeout", type=int, default=12)
    args = parser.parse_args()
    path = (ROOT / args.file).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("topics"), list):
        raise ValueError("Ожидается JSON-объект с массивом topics.")
    report = build_report(data, args.timeout)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    report_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        report_path = (ROOT / args.report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text + "\\n", encoding="utf-8")
    print(report_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

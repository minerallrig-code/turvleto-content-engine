#!/usr/bin/env python3
"""Check URL transport, redirects and page-text relevance signals.

This is a technical/editorial aid. It cannot establish factual accuracy or prove
that a page supports a claim.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
from html.parser import HTMLParser
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STOPWORDS = {
    "это", "как", "что", "для", "или", "при", "во", "в", "на", "из", "по",
    "the", "and", "for", "with", "from", "your", "this", "that", "are",
}


class PageTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.skip_depth = 0
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self.in_title = True
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value:
            return
        if self.in_title:
            self.title_parts.append(value)
        if not self.skip_depth:
            self.text_parts.append(value)


def tokens(value: str) -> set[str]:
    words = re.findall(r"[a-zа-яё0-9]{3,}", value.lower())
    return {word.replace("ё", "е") for word in words if word not in STOPWORDS}


def classify_page_relevance(page_text: str, topic: dict[str, Any]) -> dict[str, Any]:
    target = " ".join([
        str(topic.get("title", "")),
        str(topic.get("destination", "")),
        " ".join(str(x) for x in topic.get("claims_to_verify", [])),
    ])
    expected = tokens(target)
    actual = tokens(page_text[:30000])
    overlap = expected & actual
    score = len(overlap) / max(1, len(expected))
    signal = "strong" if score >= 0.30 else "moderate" if score >= 0.12 else "weak"
    return {
        "relevance_signal": signal,
        "keyword_overlap": round(score, 3),
        "matched_terms": sorted(overlap)[:20],
        "note": "Лексическое совпадение — только ориентир для редактора, не подтверждение утверждений."
    }


def check_url(url: str, timeout: int = 12, topic: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(url, str) or not url.strip():
        return {"url": url or "", "reachable": False, "status": "empty_url"}
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return {"url": url, "reachable": False, "status": "invalid_url"}

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; TurvletoContentEngine/1.1)", "Accept": "text/html,text/plain;q=0.9,*/*;q=0.5"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            status_code = response.status
            content_type = response.headers.get("Content-Type", "")
            body = response.read(512 * 1024)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 429):
            status = "blocked_or_rate_limited"
        elif exc.code == 404:
            status = "not_found"
        elif exc.code >= 500:
            status = "server_error"
        else:
            status = "http_error"
        return {"url": url, "reachable": False, "http_status": exc.code, "status": status}
    except Exception as exc:
        message = str(exc)
        if "CERTIFICATE_VERIFY_FAILED" in message:
            status = "tls_error"
        elif "Name or service not known" in message or "Temporary failure in name resolution" in message or "getaddrinfo" in message:
            status = "dns_error"
        elif "timed out" in message.lower():
            status = "timeout"
        else:
            status = "connection_error"
        return {"url": url, "reachable": False, "status": status, "error": message[:300]}

    final_host = (urllib.parse.urlparse(final_url).hostname or "").lower()
    original_host = (parsed.hostname or "").lower()
    if final_url.rstrip("/") != url.rstrip("/"):
        redirect_status = "redirected_same_host" if final_host == original_host else "redirected_other_host"
    else:
        redirect_status = "reachable"

    result: dict[str, Any] = {
        "url": url,
        "reachable": True,
        "http_status": status_code,
        "final_url": final_url,
        "status": redirect_status,
        "content_type": content_type,
    }
    if "html" in content_type.lower() or "text" in content_type.lower() or body.lstrip().startswith(b"<"):
        decoded = body.decode("utf-8", errors="replace")
        parser = PageTextParser()
        try:
            parser.feed(decoded)
        except Exception:
            pass
        page_title = html.unescape(" ".join(parser.title_parts))[:300]
        page_text = html.unescape(" ".join(parser.text_parts))
        result["page_title"] = page_title
        if topic:
            result.update(classify_page_relevance(page_title + " " + page_text, topic))
    else:
        result["content_note"] = "Ответ не распознан как HTML или текст; содержание автоматически не оценивалось."
    return result


def build_report(data: dict[str, Any], timeout: int = 12) -> dict[str, Any]:
    topic_reports = []
    for topic in data.get("topics", []):
        sources = topic.get("sources", [])
        checked = []
        for source in sources:
            checked.append(check_url(source.get("url", ""), timeout, topic))
        if not sources:
            technical_status = "no_sources"
        elif all(item.get("status") in {"reachable", "redirected_same_host"} for item in checked):
            technical_status = "all_reachable"
        elif any(item.get("reachable") for item in checked):
            technical_status = "partially_reachable"
        else:
            technical_status = "none_reachable"
        topic["source_reachability"] = technical_status
        topic["source_review_status"] = "pending_editorial_review"
        topic_reports.append({
            "title": topic.get("title", ""),
            "topic_status": topic.get("status", "needs_research"),
            "technical_status": technical_status,
            "sources": checked,
            "fact_check_note": "Даже рабочая ссылка и лексическое совпадение не доказывают, что источник подтверждает утверждение. Проверьте содержание и дату публикации вручную."
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
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        report_path = (ROOT / args.report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text + "\n", encoding="utf-8")
    print(report_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

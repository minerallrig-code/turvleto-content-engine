#!/usr/bin/env python3
"""Turvleto Content Engine: theme generation, deduplication and draft preparation."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOPICS_PATH = ROOT / "config" / "topics.json"
BRAND_PATH = ROOT / "config" / "brand.json"
HISTORY_PATH = ROOT / "content" / "history.json"
DRAFTS_DIR = ROOT / "content" / "drafts"
SELECTED_DIR = ROOT / "content" / "selected"
TOPIC_PROMPT = ROOT / "prompts" / "topic-generator.md"
POST_PROMPT = ROOT / "prompts" / "post-writer.md"


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^a-zа-я0-9]+", " ", text)
    return " ".join(text.split())


def token_similarity(left: str, right: str) -> float:
    a, b = set(normalize(left).split()), set(normalize(right).split())
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_duplicate(candidate: dict[str, Any], history: list[dict[str, Any]], threshold: float) -> bool:
    title = str(candidate.get("title", ""))
    fingerprint = normalize(title)
    for old in history:
        old_title = str(old.get("title", ""))
        if fingerprint and fingerprint == normalize(old_title):
            return True
        if token_similarity(title, old_title) >= threshold:
            return True
    return False


def validate_topics(topics: Any, history: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    if not isinstance(topics, list) or len(topics) != 3:
        raise ValueError("Генератор должен вернуть ровно 3 темы.")
    accepted: list[dict[str, Any]] = []
    seen: list[dict[str, Any]] = list(history)
    required = {"title", "destination", "category", "reader_value", "angle", "freshness_reason", "claims_to_verify", "sources", "status"}
    for item in topics:
        if not isinstance(item, dict) or not required.issubset(item):
            raise ValueError("Тема имеет неверную структуру или обязательные поля.")
        if not all(isinstance(item[k], str) and item[k].strip() for k in ("title", "destination", "category", "reader_value", "angle", "freshness_reason", "status")):
            raise ValueError("Пустое обязательное текстовое поле в теме.")
        if item["status"] not in {"proposed", "needs_research"}:
            raise ValueError("status должен быть proposed или needs_research.")
        if not isinstance(item["sources"], list) or not isinstance(item["claims_to_verify"], list):
            raise ValueError("sources и claims_to_verify должны быть массивами.")
        for source in item["sources"]:
            if not isinstance(source, dict):
                raise ValueError("Каждый источник должен быть объектом.")
            if not all(isinstance(source.get(key), str) and source[key].strip() for key in ("title", "url", "source_type")):
                raise ValueError("У каждого источника должны быть непустые title, url и source_type.")
            if not source["url"].startswith(("https://", "http://")):
                raise ValueError("Ссылка источника должна начинаться с http:// или https://.")
        if item["status"] == "proposed" and (not item["sources"] or item["claims_to_verify"]):
            raise ValueError("Тема без источников или с непроверенными утверждениями должна иметь статус needs_research.")
        if is_duplicate(item, seen, threshold):
            raise ValueError(f"Обнаружен повтор темы: {item['title']}")
        seen.append(item)
        accepted.append(item)
    return accepted


def call_openai(system_prompt: str, user_payload: dict[str, Any]) -> Any:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Не задан OPENAI_API_KEY. Добавьте ключ в GitHub Actions Secrets.")
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.7
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ошибка OpenAI API ({exc.code}): {detail[:1000]}") from exc
    content = result["choices"][0]["message"]["content"]
    return json.loads(content)


def request_valid_topics(config: dict[str, Any], history: list[dict[str, Any]], prompt: str, max_attempts: int = 3) -> list[dict[str, Any]]:
    """Retry generation when the model proposes a duplicate; never accept it."""
    threshold = float(config.get("duplicate_similarity_threshold", 0.72))
    rejected_titles: list[str] = []
    last_error: DuplicateTopicError | None = None
    for attempt in range(1, max_attempts + 1):
        payload = {
            "date": dt.date.today().isoformat(),
            "configuration": config,
            "recent_history": history[-250:],
            "rejected_titles_this_run": rejected_titles,
            "retry_instruction": (
                "Предыдущая попытка содержала повтор. Не используй эти заголовки и не перефразируй их. Выбери другие задачи туристов и ракурсы."
                if rejected_titles else ""
            ),
            "required_output": "JSON object with key topics containing exactly 3 topic objects",
        }
        result = call_openai(prompt, payload)
        topics = result.get("topics") if isinstance(result, dict) else result
        try:
            return validate_topics(topics, history, threshold)
        except DuplicateTopicError as exc:
            last_error = exc
            rejected_titles.append(str(exc).split("Обнаружен повтор темы: ", 1)[-1])
            print(f"Предупреждение: попытка {attempt}/{max_attempts} отклонена из-за повтора. Запрашиваю другие темы.", file=sys.stderr)
    raise RuntimeError(f"Не удалось получить 3 уникальные темы за {max_attempts} попытки. Последний повтор: {last_error}. История не изменена.")

def generate_topics() -> list[dict[str, Any]]:
    config = read_json(TOPICS_PATH)
    history = read_json(HISTORY_PATH).get("items", [])
    prompt = TOPIC_PROMPT.read_text(encoding="utf-8")
    accepted = request_valid_topics(config, history, prompt)
    today = dt.date.today().isoformat()
    for item in accepted:
        item["created_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        item["date"] = today
        item["source_review_status"] = "pending"
    history.extend(accepted)
    write_json(HISTORY_PATH, {"schema_version": 1, "items": history})
    output = {"date": today, "topics": accepted, "approval_required": True}
    write_json(SELECTED_DIR / f"topics-{today}.json", output)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return accepted

def write_draft(topic_file: Path, topic_index: int) -> Path:
    selected = read_json(topic_file)
    topics = selected.get("topics", [])
    if topic_index < 1 or topic_index > len(topics):
        raise ValueError("Номер темы вне диапазона.")
    topic = topics[topic_index - 1]
    prompt = POST_PROMPT.read_text(encoding="utf-8")
    result = call_openai(prompt, {"brand": read_json(BRAND_PATH), "topic": topic, "instruction": "Return JSON with telegram, max, cover_idea, editor_notes."})
    if not isinstance(result, dict) or not all(k in result for k in ("telegram", "max", "cover_idea", "editor_notes")):
        raise ValueError("Модель вернула некорректный формат черновика.")
    date = selected.get("date", dt.date.today().isoformat())
    output = {"date": date, "topic": topic, "draft": result, "status": "draft_requires_human_approval", "published": False}
    path = DRAFTS_DIR / f"{date}-topic-{topic_index}.json"
    write_json(path, output)
    print(f"Черновик сохранён: {path.relative_to(ROOT)}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Turvleto Content Engine")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", help="Сформировать ровно 3 новые темы")
    draft = sub.add_parser("draft", help="Создать черновики Telegram и MAX по выбранной теме")
    draft.add_argument("--file", required=True, help="Путь к JSON с предложенными темами")
    draft.add_argument("--topic", required=True, type=int, help="Номер темы: 1, 2 или 3")
    args = parser.parse_args()
    try:
        if args.command == "generate":
            generate_topics()
        else:
            write_draft((ROOT / args.file).resolve(), args.topic)
    except Exception as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

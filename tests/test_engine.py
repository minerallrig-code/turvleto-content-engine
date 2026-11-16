import importlib.util
import unittest
from unittest.mock import patch
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "content_engine.py"
spec = importlib.util.spec_from_file_location("content_engine", MODULE_PATH)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


class ContentEngineTests(unittest.TestCase):
    def test_normalize_yo_and_punctuation(self):
        self.assertEqual(engine.normalize("Ёлка — НЯЧАНГ!"), "елка нячанг")

    def test_similarity(self):
        self.assertGreater(engine.token_similarity("экскурсии Нячанг острова", "острова экскурсии Нячанг"), 0.9)

    def test_duplicate_exact(self):
        history = [{"title": "Как добраться до аэропорта Нячанга"}]
        self.assertTrue(engine.is_duplicate({"title": "Как добраться до аэропорта Нячанга"}, history, 0.7))

    def test_validate_requires_exactly_three(self):
        with self.assertRaises(ValueError):
            engine.validate_topics([], [], 0.7)

    def test_validate_rejects_duplicate(self):
        item = {
            "title": "Новая тема про транспорт",
            "destination": "Нячанг",
            "category": "Транспорт",
            "reader_value": "Практическая польза",
            "angle": "Совет",
            "freshness_reason": "Актуально для туристов",
            "claims_to_verify": [],
            "sources": [],
            "status": "needs_research"
        }
        with self.assertRaises(ValueError):
            engine.validate_topics([item, item, {**item, "title": "Третья тема"}], [], 0.7)


    @patch.object(engine, "call_openai")
    def test_generation_retries_when_model_returns_historical_duplicate(self, mocked_call):
        def topic(title):
            return {
                "title": title, "destination": "Нячанг", "category": "Практические советы",
                "reader_value": "Польза туристу", "angle": "Практический разбор",
                "freshness_reason": "Полезно для планирования поездки",
                "claims_to_verify": ["Проверить информацию"], "sources": [],
                "status": "needs_research"
            }
        history = [{"title": "Как оформить медицинскую страховку для путешествия во Вьетнам: практические рекомендации"}]
        duplicate_batch = [topic(history[0]["title"]), topic("Вторая тема"), topic("Третья тема")]
        fresh_batch = [topic("Пляжи Нячанга: как выбрать место для отдыха"), topic("Поездка на автобусе по Кханьхоа"), topic("Что взять с собой на экскурсию") ]
        mocked_call.side_effect = [{"topics": duplicate_batch}, {"topics": fresh_batch}]
        accepted = engine.request_valid_topics({"duplicate_similarity_threshold": 0.72}, history, "prompt")
        self.assertEqual(len(accepted), 3)
        self.assertEqual(accepted[0]["title"], fresh_batch[0]["title"])
        self.assertEqual(mocked_call.call_count, 2)
        self.assertEqual(len(history), 1)

if __name__ == "__main__":
    unittest.main()

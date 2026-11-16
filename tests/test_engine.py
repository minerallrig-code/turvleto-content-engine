import importlib.util
import unittest
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


if __name__ == "__main__":
    unittest.main()

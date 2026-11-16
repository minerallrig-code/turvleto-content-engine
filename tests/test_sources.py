import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "check_sources.py"
spec = importlib.util.spec_from_file_location("check_sources", MODULE_PATH)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class SourceCheckerTests(unittest.TestCase):
    def test_empty_url_is_rejected(self):
        result = checker.check_url("")
        self.assertFalse(result["reachable"])
        self.assertEqual(result["status"], "empty_url")

    def test_invalid_scheme_is_rejected(self):
        result = checker.check_url("ftp://example.com")
        self.assertFalse(result["reachable"])
        self.assertEqual(result["status"], "invalid_url")

    @patch.object(checker, "check_url", return_value={"url": "https://example.com", "reachable": True, "status": "reachable"})
    def test_reachable_url_does_not_upgrade_editorial_status(self, mocked):
        data = {
            "date": "2026-11-16",
            "topics": [{
                "title": "Тестовая тема",
                "status": "needs_research",
                "sources": [{"title": "Example", "url": "https://example.com", "source_type": "test"}]
            }]
        }
        report = checker.build_report(data)
        self.assertEqual(report["topics"][0]["technical_status"], "all_reachable")
        self.assertEqual(data["topics"][0]["status"], "needs_research")
        self.assertEqual(data["topics"][0]["source_review_status"], "pending_editorial_review")
        self.assertTrue(report["editorial_approval_required"])

    def test_topic_without_sources_is_reported(self):
        data = {"topics": [{"title": "Без источников", "status": "needs_research", "sources": []}]}
        report = checker.build_report(data)
        self.assertEqual(report["topics"][0]["technical_status"], "no_sources")


    def test_relevance_signal_uses_page_text_but_is_not_fact_check(self):
        topic = {
            "title": "Безопасность мотоцикл Муйне",
            "destination": "Муйне",
            "claims_to_verify": ["Правила безопасности мотоцикл"]
        }
        result = checker.classify_page_relevance(
            "Безопасность мотоцикл Муйне правила безопасности туристов",
            topic
        )
        self.assertIn(result["relevance_signal"], {"moderate", "strong"})
        self.assertIn("не подтверждение", result["note"])

    def test_empty_source_list_keeps_manual_review(self):
        data = {"topics": [{"title": "Тема", "status": "needs_research", "sources": []}]}
        report = checker.build_report(data)
        self.assertEqual(report["topics"][0]["technical_status"], "no_sources")
        self.assertEqual(data["topics"][0]["source_review_status"], "pending_editorial_review")


if __name__ == "__main__":
    unittest.main()

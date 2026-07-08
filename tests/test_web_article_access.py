from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import app.web as web
from app.utils.datetime import today_str


class WebArticleAccessTests(unittest.TestCase):
    def test_safe_today_article_path_accepts_latest_article_only(self) -> None:
        old_output = web.OUTPUT_DIR
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            web.OUTPUT_DIR = root
            folder = root / "articles" / today_str() / "latest"
            folder.mkdir(parents=True)
            article = folder / "01_test.md"
            article.write_text("# Толық мақала\n\nbody", encoding="utf-8")

            self.assertEqual(web.safe_today_article_path("01_test.md"), article.resolve())
            self.assertEqual(web.safe_today_article_path(web.display_path(article)), article.resolve())
            self.assertIsNone(web.safe_today_article_path("../01_test.md"))
            self.assertIsNone(web.safe_today_article_path(str(root / "articles" / "old" / "latest" / "01_test.md")))
        web.OUTPUT_DIR = old_output


if __name__ == "__main__":
    unittest.main()

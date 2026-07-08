from __future__ import annotations

import unittest

from app.services.article_writer import (
    build_repair_prompt,
    detect_generic_speculation,
    detect_unsupported_claims,
    event_based_title,
    find_gibberish_pattern,
    has_unsupported_casualty_claim,
    slot_matches_cluster,
    unsupported_specific_claim_reason,
)
from app.services.classifier import classify_item
from app.services.relevance import is_relevant_item


def cluster_from_item(item: dict) -> dict:
    return {
        "title": item["title"],
        "summary": item.get("summary", ""),
        "tags": item.get("tags", []),
        "sources": [item.get("source", "Test")],
        "links": [{"title": item["title"], "source": item.get("source", "Test"), "url": item.get("url", "")}],
        "final_score": item.get("final_score", 0),
        "source_count": 1,
        "max_source_score": item.get("source_score", 0),
    }


class ArticleRegressionTests(unittest.TestCase):
    def test_typhoon_maysak_is_rejected_before_china_slot(self) -> None:
        item = classify_item(
            {
                "title": "Typhoon Maysak kills two and forces thousands to evacuate in China",
                "summary": "",
                "source": "Test",
                "url": "https://example.test/typhoon",
            }
        )
        cluster = cluster_from_item(item)

        self.assertFalse(is_relevant_item(item))
        self.assertFalse(slot_matches_cluster("china_influence", cluster))

    def test_china_missile_title_matches_china_influence_slot(self) -> None:
        item = classify_item(
            {
                "title": "China's missile test builds on Pacific nuclear deterrence",
                "summary": "",
                "source": "Test",
                "url": "https://example.test/china-missile",
            }
        )
        cluster = cluster_from_item(item)

        self.assertTrue(is_relevant_item(item))
        self.assertTrue(slot_matches_cluster("china_influence", cluster))

    def test_fallback_headline_is_not_word_replaced_mixed_language(self) -> None:
        headline = event_based_title(
            {
                "title": "Belarus gets squeezed as Putin seeks war help and Ukraine threatens strikes",
                "summary": "",
                "tags": ["russia", "ukraine", "war"],
                "sources": ["Test"],
                "links": [],
            }
        )

        self.assertEqual(headline, "Беларусь Ресей мен Украина соғысының қысымында қалды")
        self.assertNotIn("gets squeezed", headline)
        self.assertNotIn("strikes", headline)

    def test_un_discussion_is_not_gibberish_after_loanword_cleanup(self) -> None:
        text = "БҰҰ Қауіпсіздік Кеңесі шұғыл сессияда Иран шабуылы туралы хабарды талқылады."

        self.assertIsNone(find_gibberish_pattern(text.lower()))

    def test_debate_to_decision_is_claim_upgrade(self) -> None:
        cluster = {
            "title": "General Assembly LIVE: Debating US sanctions against Cuba",
            "summary": "",
            "tags": ["usa", "sanctions"],
            "sources": ["UN News"],
            "links": [
                {
                    "title": "General Assembly LIVE: Debating US sanctions against Cuba",
                    "source": "UN News",
                    "url": "https://example.test/cuba",
                }
            ],
        }
        article = "Генерал Ассамблеяның шешімі санкцияларды жеңілдету туралы ұсыныстарды қамти алады."

        self.assertEqual(unsupported_specific_claim_reason(article, cluster), "unsupported_claim_upgrade")

    def test_qualified_numbers_preserve_qualifier(self) -> None:
        source = "Ukraine: Latest Russian assault leaves at least 14 dead in Kyiv"

        self.assertFalse(has_unsupported_casualty_claim("кемінде 14 адам қаза тапты", source))
        self.assertTrue(has_unsupported_casualty_claim("14 адам қаза тапты", source))

    def test_attack_is_not_artillery_attack_without_evidence(self) -> None:
        cluster = {
            "title": "Russian attack hits Kyiv",
            "summary": "",
            "tags": ["russia", "ukraine", "war"],
            "sources": ["Test"],
            "links": [{"title": "Russian attack hits Kyiv", "source": "Test", "url": "https://example.test"}],
        }
        article = "Киевке артиллериялық шабуыл жасалды."

        self.assertEqual(unsupported_specific_claim_reason(article, cluster), "unsupported_specificity")
        self.assertEqual(detect_unsupported_claims(article, cluster)[0]["code"], "unsupported_specificity")

    def test_missile_fallback_preserves_event_without_taiwan(self) -> None:
        cluster = {
            "title": "China's missile test builds on Pacific nuclear deterrence",
            "summary": "",
            "tags": ["china", "china_influence", "military", "nuclear"],
            "sources": ["Test"],
            "links": [],
        }

        headline = event_based_title(cluster)

        self.assertIn("Қытай", headline)
        self.assertRegex(headline, "зымыран|сына")
        self.assertNotIn("Тайвань", headline)

    def test_repair_prompt_targets_date_only(self) -> None:
        prompt = build_repair_prompt(
            {"title": "Test", "summary": "", "links": [], "sources": []},
            ["unsupported_date_claim"],
            [{"code": "unsupported_date_claim", "claim": "2026 жылы кездесу өтті", "evidence": "Meeting held"}],
            "Title: Test",
            "# Тақырып\n\n**Лид:**\n2026 жылы кездесу өтті.",
        )

        self.assertIn("датаны ғана алып таста", prompt)
        self.assertIn("Fix only listed issues", prompt)

    def test_generic_speculation_is_flagged(self) -> None:
        claims = detect_generic_speculation("Алдағы уақытта шешімдер қабылдануы мүмкін.")

        self.assertEqual(claims[0]["code"], "generic_speculation")


if __name__ == "__main__":
    unittest.main()

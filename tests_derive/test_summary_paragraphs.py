"""Gate 1A: multi-paragraph summary recovery in both parser families.

Both parsers used to end a summary at the first blank line, silently discarding every
following editorial paragraph. These tests pin the corrected boundary rules: a blank
line only ends the summary when what follows is a definite next article, a section
heading, or a structural boundary.
"""

from __future__ import annotations

import unittest

from tools.tldr_derive.parser_inline import parse_inline_url
from tools.tldr_derive.parser_references import parse_links_block

ISSUE_ID = "tldr:2024-06-18"


def inline_issue(body: str) -> str:
    return f"TLDR\n\n{body}"


def links_issue(body: str, links: str = "[1] https://example.com/a\n") -> str:
    return f"TLDR\n\n{body}\nLinks:\n{links}"


def articles(text: str):
    """Flatten the articles of whichever format the body uses."""
    parse = parse_links_block if "Links:" in text else parse_inline_url
    sections, _ = parse(text, ISSUE_ID)
    return [article for section in sections for article in section.articles]


class InlineFormatParagraphs(unittest.TestCase):
    def test_single_paragraph_summary_is_unchanged(self) -> None:
        body = (
            "BIG TECH & STARTUPS\n\n"
            "A FIRST STORY (2 MINUTE READ)\n"
            "[https://example.com/one]\n\n"
            "Only one paragraph here.\n"
        )
        found = articles(inline_issue(body))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].summary, "Only one paragraph here.")
        self.assertNotIn("\n", found[0].summary)

    def test_two_paragraph_summary_is_recovered(self) -> None:
        body = (
            "BIG TECH & STARTUPS\n\n"
            "A FIRST STORY (2 MINUTE READ)\n"
            "[https://example.com/one]\n\n"
            "First paragraph of the blurb.\n\n"
            "Second paragraph that used to be lost.\n"
        )
        found = articles(inline_issue(body))
        self.assertEqual(len(found), 1)
        self.assertEqual(
            found[0].summary,
            "First paragraph of the blurb.\n\nSecond paragraph that used to be lost.",
        )

    def test_three_paragraph_summary_is_recovered(self) -> None:
        body = (
            "BIG TECH & STARTUPS\n\n"
            "A FIRST STORY (2 MINUTE READ)\n"
            "[https://example.com/one]\n\n"
            "Para one.\n\nPara two.\n\nPara three.\n"
        )
        found = articles(inline_issue(body))
        self.assertEqual(found[0].summary, "Para one.\n\nPara two.\n\nPara three.")

    def test_blank_line_before_next_article_ends_the_summary(self) -> None:
        body = (
            "BIG TECH & STARTUPS\n\n"
            "A FIRST STORY (2 MINUTE READ)\n"
            "[https://example.com/one]\n\n"
            "Belongs to the first story.\n\n"
            "A SECOND STORY (3 MINUTE READ)\n"
            "[https://example.com/two]\n\n"
            "Belongs to the second story.\n"
        )
        found = articles(inline_issue(body))
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0].summary, "Belongs to the first story.")
        self.assertEqual(found[1].summary, "Belongs to the second story.")

    def test_blank_line_before_next_section_ends_the_summary(self) -> None:
        body = (
            "BIG TECH & STARTUPS\n\n"
            "A FIRST STORY (2 MINUTE READ)\n"
            "[https://example.com/one]\n\n"
            "Belongs to the first story.\n\n"
            "SCIENCE & FUTURISTIC TECHNOLOGY\n\n"
            "ANOTHER STORY (1 MINUTE READ)\n"
            "[https://example.com/three]\n\n"
            "Different section.\n"
        )
        found = articles(inline_issue(body))
        self.assertEqual(found[0].summary, "Belongs to the first story.")
        self.assertNotIn("SCIENCE", found[0].summary)

    def test_uppercase_continuation_is_not_mistaken_for_a_title(self) -> None:
        # The weak all-uppercase heuristic must not apply across a blank line.
        body = (
            "BIG TECH & STARTUPS\n\n"
            "A FIRST STORY (2 MINUTE READ)\n"
            "[https://example.com/one]\n\n"
            "Opening paragraph.\n\n"
            "THIS CONTINUATION IS SHOUTED BUT IT IS STILL PROSE.\n"
        )
        found = articles(inline_issue(body))
        self.assertEqual(len(found), 1)
        self.assertIn("SHOUTED", found[0].summary)


class LinksBlockFormatParagraphs(unittest.TestCase):
    def test_preamble_keeps_first_line_of_wrapped_lead_title(self) -> None:
        # Production regression from TLDR Data 2026-08-03. The old preamble scan
        # started at the marker-only second line and published the title "MINUTE READ)".
        body = (
            "DEEP DIVES\n\n"
            "HOW DOORDASH BUILT A CENTRALIZED GATEWAY FOR AI AGENT-TOOL ACCESS (13\n"
            "MINUTE READ) [4]\n\n"
            "DoorDash built a centralized Agent Gateway for governed tool access.\n"
        )
        found = articles(links_issue(body, "[4] https://example.com/doordash\n"))
        self.assertEqual(len(found), 1)
        self.assertEqual(
            found[0].title,
            "HOW DOORDASH BUILT A CENTRALIZED GATEWAY FOR AI AGENT-TOOL ACCESS",
        )
        self.assertEqual(found[0].reading_time_minutes, 13)

    def test_single_paragraph_summary_is_unchanged(self) -> None:
        body = "BIG TECH & STARTUPS\n\nA FIRST STORY (2 MINUTE READ) [1]\n\nOnly one paragraph.\n"
        found = articles(links_issue(body))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].summary, "Only one paragraph.")

    def test_two_paragraph_summary_is_recovered(self) -> None:
        body = "BIG TECH & STARTUPS\n\nA FIRST STORY (2 MINUTE READ) [1]\n\nFirst para.\n\nSecond para.\n"
        found = articles(links_issue(body))
        self.assertEqual(found[0].summary, "First para.\n\nSecond para.")

    def test_blank_line_before_next_article_ends_the_summary(self) -> None:
        body = (
            "BIG TECH & STARTUPS\n\n"
            "A FIRST STORY (2 MINUTE READ) [1]\n\n"
            "First story blurb.\n\n"
            "A SECOND STORY (3 MINUTE READ) [2]\n\n"
            "Second story blurb.\n"
        )
        found = articles(links_issue(body, "[1] https://example.com/a\n[2] https://example.com/b\n"))
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0].summary, "First story blurb.")
        self.assertEqual(found[1].summary, "Second story blurb.")

    def test_link_definition_block_never_enters_a_summary(self) -> None:
        body = "BIG TECH & STARTUPS\n\nA FIRST STORY (2 MINUTE READ) [1]\n\nThe blurb.\n"
        found = articles(links_issue(body))
        self.assertNotIn("https://", found[0].summary)
        self.assertNotIn("[1]", found[0].summary)

    def test_quick_links_multi_paragraph_item_keeps_its_second_paragraph(self) -> None:
        # The structural equivalent of the dan@tldr.tech case: a QUICK LINKS entry whose
        # contact details live in a second paragraph.
        body = (
            "QUICK LINKS\n\n"
            "LOOKING FOR A TALENTED OPERATOR? (LINKEDIN PROFILE) [1]\n\n"
            "A close friend of mine is looking for his next mission, ideally a\n"
            "director-level role in healthcare.\n\n"
            "A+ player and human being, he was most recently a Director at Redesign\n"
            "Health, ping me at contact@example.com to connect!\n"
        )
        found = articles(links_issue(body))
        self.assertEqual(len(found), 1)
        self.assertIn("contact@example.com", found[0].summary)
        self.assertIn("Redesign", found[0].summary)
        self.assertIn("\n\n", found[0].summary)


class FooterAndMalformedBoundaries(unittest.TestCase):
    def test_subscription_footer_never_enters_a_summary(self) -> None:
        body = (
            "BIG TECH & STARTUPS\n\n"
            "A FIRST STORY (2 MINUTE READ) [1]\n\n"
            "The editorial blurb.\n\n"
            "Want to advertise in TLDR? Find out more here\n\n"
            "If you have any comments or feedback, just respond to this email!\n\n"
            "Manage your subscriptions to our other newsletters on tldr.tech or\n"
            "unsubscribe from TLDR.\n"
        )
        found = articles(links_issue(body))
        summary = found[0].summary
        self.assertNotIn("unsubscribe", summary.lower())
        self.assertNotIn("manage your subscriptions", summary.lower())

    def test_summary_at_end_of_input_terminates_cleanly(self) -> None:
        body = "BIG TECH & STARTUPS\n\nA FIRST STORY (2 MINUTE READ) [1]\n\nTrailing paragraph with no newline after"
        found = articles(links_issue(body))
        self.assertEqual(found[0].summary, "Trailing paragraph with no newline after")

    def test_repeated_blank_lines_do_not_split_into_empty_paragraphs(self) -> None:
        body = "BIG TECH & STARTUPS\n\nA FIRST STORY (2 MINUTE READ) [1]\n\nFirst.\n\n\n\nSecond.\n"
        found = articles(links_issue(body))
        self.assertEqual(found[0].summary, "First.\n\nSecond.")
        self.assertNotIn("\n\n\n", found[0].summary)

    def test_article_with_no_summary_stays_empty(self) -> None:
        body = (
            "BIG TECH & STARTUPS\n\n"
            "A FIRST STORY (2 MINUTE READ) [1]\n\n"
            "A SECOND STORY (3 MINUTE READ) [2]\n\n"
            "Only the second has a blurb.\n"
        )
        found = articles(links_issue(body, "[1] https://example.com/a\n[2] https://example.com/b\n"))
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0].summary, "")
        self.assertEqual(found[1].summary, "Only the second has a blurb.")


class DerivationDeterminism(unittest.TestCase):
    def test_two_identical_runs_produce_identical_summaries(self) -> None:
        body = (
            "BIG TECH & STARTUPS\n\n"
            "A FIRST STORY (2 MINUTE READ) [1]\n\n"
            "Para one.\n\nPara two.\n\nPara three.\n"
        )
        first = [a.summary for a in articles(links_issue(body))]
        second = [a.summary for a in articles(links_issue(body))]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

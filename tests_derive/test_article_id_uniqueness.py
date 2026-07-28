"""Gate 1B: article ids must be unique, stable, and minimally churned."""

from __future__ import annotations

import unittest

from tools.tldr_derive.parser_references import parse_links_block

ISSUE_ID = "tldr:2024-05-06"


def issue(body: str, links: str) -> str:
    return f"TLDR\n\n{body}\nLinks:\n{links}"


def ids(text: str) -> list[str]:
    sections, _ = parse_links_block(text, ISSUE_ID)
    return [a.id for s in sections for a in s.articles]


class ArticleIdUniqueness(unittest.TestCase):
    def test_distinct_reference_numbers_keep_their_historical_ids(self) -> None:
        body = (
            "BIG TECH & STARTUPS\n\n"
            "FIRST STORY (2 MINUTE READ) [4]\n\nBlurb one.\n\n"
            "SECOND STORY (3 MINUTE READ) [5]\n\nBlurb two.\n"
        )
        found = ids(issue(body, "[4] https://example.com/a\n[5] https://example.com/b\n"))
        self.assertEqual(found, [f"{ISSUE_ID}:a04", f"{ISSUE_ID}:a05"])

    def test_repeated_reference_number_is_suffixed_deterministically(self) -> None:
        # The real shape: an article followed by its own call-to-action line, which the
        # parser reads as a second entry carrying the same reference number.
        body = (
            "BIG TECH & STARTUPS\n\n"
            "FROM COST CENTER TO TRUST CENTER (2 MINUTE READ) [11]\n\n"
            "The sponsored blurb.\n\n"
            "SEE THE PRODUCT IN ACTION (2 MINUTE READ) [11]\n"
        )
        found = ids(issue(body, "[11] https://example.com/demo\n"))
        self.assertEqual(found, [f"{ISSUE_ID}:a11", f"{ISSUE_ID}:a11-02"])

    def test_first_occurrence_never_changes(self) -> None:
        body = (
            "BIG TECH & STARTUPS\n\n"
            "ONE (2 MINUTE READ) [7]\n\nA.\n\n"
            "TWO (2 MINUTE READ) [7]\n\nB.\n\n"
            "THREE (2 MINUTE READ) [7]\n\nC.\n"
        )
        found = ids(issue(body, "[7] https://example.com/x\n"))
        self.assertEqual(found[0], f"{ISSUE_ID}:a07")
        self.assertEqual(found, [f"{ISSUE_ID}:a07", f"{ISSUE_ID}:a07-02", f"{ISSUE_ID}:a07-03"])

    def test_every_article_keeps_exactly_one_id_and_none_disappear(self) -> None:
        body = (
            "BIG TECH & STARTUPS\n\n"
            "ONE (2 MINUTE READ) [7]\n\nA.\n\n"
            "TWO (2 MINUTE READ) [7]\n\nB.\n\n"
            "THREE (2 MINUTE READ) [8]\n\nC.\n"
        )
        found = ids(issue(body, "[7] https://example.com/x\n[8] https://example.com/y\n"))
        self.assertEqual(len(found), 3)
        self.assertEqual(len(set(found)), 3)

    def test_ids_are_stable_across_two_identical_runs(self) -> None:
        body = (
            "BIG TECH & STARTUPS\n\n"
            "ONE (2 MINUTE READ) [7]\n\nA.\n\n"
            "TWO (2 MINUTE READ) [7]\n\nB.\n"
        )
        text = issue(body, "[7] https://example.com/x\n")
        self.assertEqual(ids(text), ids(text))

    def test_suffix_does_not_depend_on_summary_text(self) -> None:
        # Gate 1A changes summaries; ids must not move because of it.
        short = (
            "BIG TECH & STARTUPS\n\n"
            "ONE (2 MINUTE READ) [7]\n\nA.\n\n"
            "TWO (2 MINUTE READ) [7]\n\nB.\n"
        )
        long = (
            "BIG TECH & STARTUPS\n\n"
            "ONE (2 MINUTE READ) [7]\n\nA.\n\nA second recovered paragraph.\n\n"
            "TWO (2 MINUTE READ) [7]\n\nB.\n\nAnother recovered paragraph.\n"
        )
        links = "[7] https://example.com/x\n"
        self.assertEqual(ids(issue(short, links)), ids(issue(long, links)))

    def test_a_suffixed_id_never_collides_with_a_real_reference(self) -> None:
        body = (
            "BIG TECH & STARTUPS\n\n"
            "ONE (2 MINUTE READ) [7]\n\nA.\n\n"
            "TWO (2 MINUTE READ) [7]\n\nB.\n\n"
            "THREE (2 MINUTE READ) [70]\n\nC.\n"
        )
        found = ids(issue(body, "[7] https://example.com/x\n[70] https://example.com/z\n"))
        self.assertEqual(len(set(found)), len(found))
        self.assertIn(f"{ISSUE_ID}:a70", found)
        self.assertIn(f"{ISSUE_ID}:a07-02", found)


if __name__ == "__main__":
    unittest.main()

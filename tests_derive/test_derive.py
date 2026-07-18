"""Safe offline unit tests for tools.tldr_derive (stdlib unittest)."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.tldr_derive import GENERATOR_VERSION, SCHEMA_VERSION
from tools.tldr_derive.cli import main
from tools.tldr_derive.discovery import (
    SourceContainmentError,
    content_sha256,
    discover_sources,
    parse_filename_date,
    resolve_source,
    sector_slug,
)
from tools.tldr_derive.models import issue_to_canonical_json
from tools.tldr_derive.parser import parse_source
from tools.tldr_derive.parser_common import detect_format_family
from tools.tldr_derive.sanitizer import (
    is_private_url,
    normalize_public_url,
    repair_wrapped_url,
    strip_zero_width,
    truncate_footer,
)
from tools.tldr_derive.writer import (
    OutputContainmentError,
    atomic_write_text,
    build_manifest_entries,
    ensure_within,
    filter_changed,
    load_manifest_entries_by_source,
    validate_output_root,
    write_issue,
    write_manifest,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "repo"


class DiscoveryTests(unittest.TestCase):
    def test_sector_discovery_and_exclusion(self) -> None:
        sources = discover_sources(FIXTURES)
        paths = {s.relative_path for s in sources}
        self.assertIn("TLDR AI/article_16-02-2023.md", paths)
        self.assertIn("TLDR AI/article_16-07-2026.md", paths)
        self.assertIn("TLDR/article_17-01-2023.md", paths)
        self.assertIn("TLDR/article_15-03-2024.md", paths)
        self.assertIn("TLDR/article_08-02-2023.md", paths)
        self.assertIn("TLDR/article_27-01-2023.md", paths)
        self.assertIn("TLDR Crypto/article_01-01-2024.md", paths)
        self.assertTrue(all(not p.startswith("NotTLDR") for p in paths))
        self.assertTrue(all("GoDaddy" not in p for p in paths))
        self.assertEqual(len(sources), 7)

    def test_filename_date_extraction(self) -> None:
        self.assertEqual(
            parse_filename_date("article_16-07-2026.md"),
            ("2026-07-16", "16-07-2026"),
        )
        self.assertIsNone(parse_filename_date("article_99-99-2026.md"))
        self.assertIsNone(parse_filename_date("notes.md"))

    def test_sector_slug(self) -> None:
        self.assertEqual(sector_slug("TLDR AI"), "tldr-ai")
        self.assertEqual(sector_slug("TLDR"), "tldr")
        self.assertEqual(sector_slug("TLDR Web Dev"), "tldr-web-dev")

    def test_source_hashing(self) -> None:
        path = FIXTURES / "TLDR AI" / "article_16-07-2026.md"
        raw = path.read_bytes()
        expected = "sha256:" + hashlib.sha256(raw).hexdigest()
        self.assertEqual(content_sha256(raw), expected)

    def test_resolve_source_rejects_sibling_prefix_path(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="tldr_prefix_"))
        try:
            root = base / "repo"
            sibling = base / "repo_evil"
            (root / "TLDR").mkdir(parents=True)
            (sibling / "TLDR").mkdir(parents=True)
            evil = sibling / "TLDR" / "article_01-01-2024.md"
            evil.write_text("# Articles TLDR 01-01-2024\n\n", encoding="utf-8")
            # String-prefix check would wrongly allow repo_evil under root=".../repo".
            self.assertTrue(str(evil.resolve()).startswith(str(root.resolve())))
            with self.assertRaises(SourceContainmentError):
                resolve_source(root, str(evil))
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_resolve_source_requires_top_level_sector(self) -> None:
        nested = FIXTURES / "TLDR" / "nested"
        # ensure path doesn't exist as valid source
        with self.assertRaises(ValueError):
            resolve_source(FIXTURES, "NotTLDR/article_01-01-2024.md")


class ParserTests(unittest.TestCase):
    def _parse(self, relative: str):
        source = resolve_source(FIXTURES, relative)
        text = source.path.read_text(encoding="utf-8")
        return source, parse_source(source, text)

    def test_format_family_detection(self) -> None:
        inline = (FIXTURES / "TLDR AI" / "article_16-02-2023.md").read_text(
            encoding="utf-8"
        )
        refs = (FIXTURES / "TLDR AI" / "article_16-07-2026.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(detect_format_family(inline), "inline_url")
        self.assertEqual(detect_format_family(refs), "links_block")

    def test_inline_url_parsing(self) -> None:
        _, issue = self._parse("TLDR AI/article_16-02-2023.md")
        self.assertEqual(issue.format_family, "inline_url")
        self.assertNotEqual(issue.parse_status, "failed")
        titles = [a.title for s in issue.sections for a in s.articles]
        self.assertTrue(any("BING AI" in t for t in titles))
        urls = [a.url for s in issue.sections for a in s.articles]
        self.assertTrue(any(u and "theverge.com" in u for u in urls))

    def test_inline_same_line_and_wrapped_urls(self) -> None:
        """Historical TITLE (N MINUTE READ) [https://...] patterns."""
        _, issue = self._parse("TLDR/article_08-02-2023.md")
        self.assertEqual(issue.format_family, "inline_url")
        arts = {a.title: a for s in issue.sections for a in s.articles}

        classic = arts["CLASSIC NEXT LINE ARTICLE"]
        self.assertEqual(classic.reading_time_minutes, 5)
        self.assertIn("theverge.com", classic.url or "")
        self.assertEqual(classic.source_domain, "theverge.com")
        self.assertIn("classic next-line", classic.summary.lower())
        self.assertNotIn("http", classic.title.lower())

        wrapped_same = arts[
            "META ASKS MANY MANAGERS TO GET BACK TO MAKING THINGS OR LEAVE"
        ]
        self.assertEqual(wrapped_same.reading_time_minutes, 2)
        self.assertTrue((wrapped_same.url or "").startswith("https://archive.ph/"))
        self.assertEqual(wrapped_same.source_domain, "archive.ph")
        self.assertIn("individual contributor", wrapped_same.summary.lower())
        self.assertNotIn("http", wrapped_same.title.lower())
        self.assertNotIn("archive.ph", wrapped_same.title.lower())

        same_line = arts["SAME LINE ARCHIVE LINK"]
        self.assertEqual(same_line.reading_time_minutes, 3)
        self.assertIn("archive.ph/tHRU8", same_line.url or "")
        self.assertEqual(same_line.source_domain, "archive.ph")
        self.assertNotIn("http", same_line.title.lower())

        wrapped_next = arts["WRAPPED READING TIME THEN NEXT LINE URL"]
        self.assertEqual(wrapped_next.reading_time_minutes, 11)
        self.assertIn("simplethread.com", wrapped_next.url or "")
        self.assertNotIn("http", wrapped_next.title.lower())

        ordinary = arts["ORDINARY DOMAIN SAME LINE"]
        self.assertEqual(ordinary.reading_time_minutes, 4)
        self.assertEqual(ordinary.url, "https://arxiv.org/abs/2302.00001")
        self.assertEqual(ordinary.source_domain, "arxiv.org")
        self.assertNotIn("http", ordinary.title.lower())

        short = arts["SHORT NEXT LINE"]
        self.assertEqual(short.reading_time_minutes, 1)
        self.assertIn("example.com/quick-next", short.url or "")

        for article in arts.values():
            self.assertNotRegex(article.title, r"https?://")

    def test_inline_next_line_urls_still_work(self) -> None:
        """Regression: existing next-line inline URLs remain intact."""
        _, issue = self._parse("TLDR AI/article_16-02-2023.md")
        arts = [a for s in issue.sections for a in s.articles]
        self.assertGreaterEqual(len(arts), 3)
        by_title = {a.title: a for a in arts}
        bing = by_title["BING AI IS UNHINGED"]
        self.assertEqual(bing.reading_time_minutes, 3)
        self.assertIn("theverge.com", bing.url or "")
        self.assertEqual(bing.source_domain, "theverge.com")
        self.assertIn("personality", bing.summary.lower())
        self.assertNotIn("http", bing.title.lower())
        human = by_title["HUMAN WRITER OR AI?"]
        self.assertEqual(human.reading_time_minutes, 5)
        self.assertIn("example.com/detectgpt", human.url or "")
        short = by_title["SHORT ITEM"]
        self.assertEqual(short.reading_time_minutes, 1)
        self.assertIn("example.com/quick", short.url or "")

    def test_reference_link_parsing(self) -> None:
        _, issue = self._parse("TLDR AI/article_16-07-2026.md")
        self.assertEqual(issue.format_family, "links_block")
        arts = [a for s in issue.sections for a in s.articles]
        self.assertGreaterEqual(len(arts), 3)
        thinking = next(a for a in arts if "THINKING MACHINES" in a.title)
        self.assertEqual(thinking.reading_time_minutes, 12)
        self.assertIsNotNone(thinking.url)
        self.assertIn("thinkingmachines.ai", thinking.url)

    def test_multiline_title_and_summary(self) -> None:
        _, issue = self._parse("TLDR/article_15-03-2024.md")
        arts = [a for s in issue.sections for a in s.articles]
        self.assertEqual(len(arts), 1)
        self.assertIn("WRAPPED URL ARTICLE TITLE", arts[0].title)
        self.assertIn("ON ANOTHER LINE", arts[0].title)
        self.assertIn("multiple lines", arts[0].summary)

    def test_sections(self) -> None:
        _, issue = self._parse("TLDR AI/article_16-07-2026.md")
        headings = [s.heading for s in issue.sections]
        self.assertIn("HEADLINES & LAUNCHES", headings)
        self.assertTrue(all(s.order >= 1 for s in issue.sections))

    def test_reading_time(self) -> None:
        _, issue = self._parse("TLDR AI/article_16-02-2023.md")
        times = [
            a.reading_time_minutes
            for s in issue.sections
            for a in s.articles
            if a.reading_time_minutes is not None
        ]
        self.assertIn(3, times)
        self.assertIn(5, times)

    def test_sponsor_and_github_content_type(self) -> None:
        _, issue = self._parse("TLDR AI/article_16-07-2026.md")
        arts = [a for s in issue.sections for a in s.articles]
        sponsor = next(a for a in arts if a.is_sponsor)
        self.assertEqual(sponsor.content_type, "sponsor")
        github = next(a for a in arts if a.content_type == "github_repo")
        self.assertIn("ANYTEXT", github.title)

    def test_dangling_reference(self) -> None:
        _, issue = self._parse("TLDR AI/article_16-07-2026.md")
        codes = [w.code for w in issue.parse_warnings]
        self.assertIn("dangling_reference", codes)
        self.assertEqual(issue.parse_status, "partial")

    def test_html_entity_decoding(self) -> None:
        _, issue = self._parse("TLDR AI/article_16-07-2026.md")
        arts = [a for s in issue.sections for a in s.articles]
        sponsor = next(a for a in arts if a.is_sponsor)
        self.assertIsNotNone(sponsor.url)
        self.assertNotIn("&amp;", sponsor.url)

    def test_zero_width_removal(self) -> None:
        text = "Hello\u200c\u200bWorld"
        self.assertEqual(strip_zero_width(text), "HelloWorld")
        raw = (FIXTURES / "TLDR AI" / "article_16-07-2026.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("\u200c", raw)
        _, issue = self._parse("TLDR AI/article_16-07-2026.md")
        blob = issue_to_canonical_json(issue)
        self.assertNotIn("\u200c", blob)

    def test_url_line_repair(self) -> None:
        repaired = repair_wrapped_url(
            "https://example.com/path/to/\narticle-page?utm_source=tldr&amp;x=1"
        )
        self.assertEqual(
            repaired,
            "https://example.com/path/to/article-page?utm_source=tldr&x=1",
        )
        _, issue = self._parse("TLDR/article_15-03-2024.md")
        url = issue.sections[0].articles[0].url
        self.assertIsNotNone(url)
        self.assertIn("article-page", url)
        self.assertNotIn("\n", url)

    def test_private_url_removal(self) -> None:
        self.assertTrue(
            is_private_url("https://tldr.tech/ai/manage?email=user@example.com")
        )
        self.assertTrue(
            is_private_url(
                "https://a.tldrnewsletter.com/unsubscribe?ep=1&s=token"
            )
        )
        self.assertIsNone(
            normalize_public_url(
                "https://tldr.tech/ai/manage?email=user@example.com"
            )
        )
        _, issue = self._parse("TLDR AI/article_16-07-2026.md")
        blob = issue_to_canonical_json(issue)
        self.assertNotIn("subscriber@example.com", blob)
        self.assertNotIn("unsubscribe", blob.lower())
        self.assertNotIn("manage?email", blob.lower())
        self.assertNotIn("sparklp", blob.lower())
        self.assertNotIn("refer.tldr.tech", blob.lower())

    def test_editorial_query_params_preserved(self) -> None:
        self.assertEqual(
            normalize_public_url("https://example.com/story?t=120&utm_source=tldr"),
            "https://example.com/story?t=120&utm_source=tldr",
        )
        self.assertEqual(
            normalize_public_url("https://example.com/x?p=article&s=abc"),
            "https://example.com/x?p=article&s=abc",
        )
        self.assertEqual(
            normalize_public_url(
                "https://news.example.com/a?token=keep&uid=keep&user_id=keep"
            ),
            "https://news.example.com/a?token=keep&uid=keep&user_id=keep",
        )

    def test_subscriber_params_never_emitted(self) -> None:
        url = normalize_public_url(
            "https://example.com/post?email=user@example.com&utm_source=tldr"
        )
        self.assertIsNotNone(url)
        self.assertNotIn("email=", url)
        self.assertIn("utm_source=tldr", url)

    def test_footer_removal(self) -> None:
        _, issue = self._parse("TLDR AI/article_16-02-2023.md")
        titles = [a.title for s in issue.sections for a in s.articles]
        self.assertFalse(any("unsubscribe" in t.lower() for t in titles))

    def test_job_board_sentence_does_not_truncate_footer(self) -> None:
        """Sponsor body 'job board. Thousands...' is not a footer heading."""
        sentence = (
            "If you're looking to hire top technical talent, sign up for our free\n"
            "job board. Thousands of engineers, designers, and other tech workers\n"
            "visit the job board each day.\n"
            "\n"
            "ARTICLE AFTER SPONSOR (3 MINUTE READ)\n"
            "[https://example.com/after-sponsor]\n"
            "\n"
            "Summary remains after the job board sentence.\n"
            "\n"
            "JOB BOARD\n"
            "\n"
            "Over a dozen more jobs are posted every day.\n"
            "\n"
            "If you don't want to receive future editions of TLDR, please click\n"
            "here to unsubscribe\n"
            "[https://actions.tldrnewsletter.com/unsubscribe?ep=1&l=secret&s=token]\n"
        )
        kept, removed = truncate_footer(sentence)
        self.assertTrue(removed)
        self.assertIn("ARTICLE AFTER SPONSOR", kept)
        self.assertIn("job board. Thousands of engineers", kept)
        self.assertNotIn("Over a dozen more jobs", kept)
        self.assertNotIn("unsubscribe", kept.lower())

        standalone_only = "Some article text\n\nJOB BOARD\n\nHire through TLDR.\n"
        kept2, removed2 = truncate_footer(standalone_only)
        self.assertTrue(removed2)
        self.assertIn("Some article text", kept2)
        self.assertNotIn("Hire through TLDR", kept2)

        jobs_heading = "Body\n\nJOBS BOARD\n\nTrailing footer copy.\n"
        kept3, removed3 = truncate_footer(jobs_heading)
        self.assertTrue(removed3)
        self.assertIn("Body", kept3)
        self.assertNotIn("Trailing footer copy", kept3)

    def test_job_board_false_positive_recovers_archive_ph_articles(self) -> None:
        """Historical sponsor copy must not drop later editorial archive.ph URLs."""
        _, issue = self._parse("TLDR/article_27-01-2023.md")
        self.assertNotEqual(issue.parse_status, "failed")
        arts = [a for s in issue.sections for a in s.articles]
        urls = [a.url or "" for a in arts]
        self.assertTrue(any("archive.ph/TvP3p" in u for u in urls))
        self.assertTrue(any("archive.ph/5dgFD" in u for u in urls))
        self.assertTrue(any("archive.ph/jErjz" in u for u in urls))
        self.assertTrue(any("archive.ph/ukO06" in u for u in urls))
        for article in arts:
            self.assertNotRegex(article.title, r"https?://")
        buzz = next(a for a in arts if a.url and "archive.ph/TvP3p" in a.url)
        self.assertEqual(buzz.reading_time_minutes, 3)
        self.assertEqual(buzz.source_domain, "archive.ph")
        self.assertIn("quizzes", buzz.summary.lower())
        # Sponsor sentence must not truncate before editorial content.
        self.assertGreaterEqual(len(arts), 4)
    def test_historical_sources_emit_recovered_archive_ph_urls(self) -> None:
        """Real corpus sources that previously lost four archive.ph URLs."""
        repo = Path(__file__).resolve().parents[1]
        expected = {
            "TLDR/article_27-01-2023.md": ("TvP3p", "5dgFD"),
            "TLDR/article_30-01-2023.md": ("jErjz",),
            "TLDR/article_31-01-2023.md": ("ukO06",),
        }
        for relative, slugs in expected.items():
            source = resolve_source(repo, relative)
            issue = parse_source(source, source.path.read_text(encoding="utf-8"))
            urls = [
                a.url or ""
                for s in issue.sections
                for a in s.articles
            ]
            for slug in slugs:
                self.assertTrue(
                    any(f"archive.ph/{slug}" in u for u in urls),
                    msg=f"{relative} missing archive.ph/{slug}",
                )
            self.assertGreater(len(urls), 1, msg=f"{relative} still truncated")

    def test_malformed_and_header_only_status(self) -> None:
        _, header = self._parse("TLDR/article_17-01-2023.md")
        self.assertEqual(header.parse_status, "failed")
        _, malformed = self._parse("TLDR Crypto/article_01-01-2024.md")
        self.assertIn(malformed.parse_status, {"failed", "partial"})

    def test_complete_partial_failed(self) -> None:
        _, wrapped = self._parse("TLDR/article_15-03-2024.md")
        self.assertEqual(wrapped.parse_status, "complete")
        _, partial = self._parse("TLDR AI/article_16-07-2026.md")
        self.assertEqual(partial.parse_status, "partial")
        _, failed = self._parse("TLDR/article_17-01-2023.md")
        self.assertEqual(failed.parse_status, "failed")


class WriterAndDeterminismTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tldr_derive_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _generate_all(self, out: Path) -> list:
        sources = discover_sources(FIXTURES)
        issues = []
        for source in sources:
            issue = parse_source(source, source.path.read_text(encoding="utf-8"))
            write_issue(out, source, issue)
            issues.append(issue)
        write_manifest(out, build_manifest_entries(issues), merge_existing=False)
        return sources

    def test_deterministic_serialization(self) -> None:
        source = resolve_source(FIXTURES, "TLDR/article_15-03-2024.md")
        issue = parse_source(source, source.path.read_text(encoding="utf-8"))
        a = issue_to_canonical_json(issue)
        b = issue_to_canonical_json(issue)
        self.assertEqual(a, b)
        self.assertTrue(a.endswith("\n"))

    def test_idempotent_generation(self) -> None:
        source = resolve_source(FIXTURES, "TLDR/article_15-03-2024.md")
        issue = parse_source(source, source.path.read_text(encoding="utf-8"))
        out = self.tmp / "generated"
        p1, payload1 = write_issue(out, source, issue)
        p2, payload2 = write_issue(out, source, issue)
        self.assertEqual(p1, p2)
        self.assertEqual(payload1, payload2)
        self.assertEqual(p1.read_text(encoding="utf-8"), payload1)

    def test_changed_skips_when_current(self) -> None:
        out = self.tmp / "generated"
        sources = self._generate_all(out)
        changed = filter_changed(sources, out)
        self.assertEqual(changed, [])

    def test_changed_on_source_hash(self) -> None:
        out = self.tmp / "generated"
        sources = self._generate_all(out)
        entries = load_manifest_entries_by_source(out)
        entries[sources[0].relative_path]["source_content_hash"] = "sha256:deadbeef"
        changed = filter_changed(sources, out, manifest_entries=entries)
        self.assertEqual([c.relative_path for c in changed], [sources[0].relative_path])

    def test_changed_on_missing_derived_json(self) -> None:
        out = self.tmp / "generated"
        sources = self._generate_all(out)
        target = (
            out
            / "issues"
            / sources[0].sector_slug
            / sources[0].date_iso[:4]
            / f"{sources[0].date_iso}.json"
        )
        target.unlink()
        changed = filter_changed(sources, out)
        self.assertEqual([c.relative_path for c in changed], [sources[0].relative_path])

    def test_changed_on_schema_version(self) -> None:
        out = self.tmp / "generated"
        sources = self._generate_all(out)
        entries = load_manifest_entries_by_source(out)
        for entry in entries.values():
            entry["schema_version"] = "0.0.0"
        changed = filter_changed(sources, out, manifest_entries=entries)
        self.assertEqual(len(changed), len(sources))

    def test_changed_on_generator_version(self) -> None:
        out = self.tmp / "generated"
        sources = self._generate_all(out)
        entries = load_manifest_entries_by_source(out)
        for entry in entries.values():
            entry["generator_version"] = "0.0.0"
        changed = filter_changed(sources, out, manifest_entries=entries)
        self.assertEqual(len(changed), len(sources))

    def test_manifest_includes_versions(self) -> None:
        out = self.tmp / "generated"
        self._generate_all(out)
        doc = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["schema_version"], SCHEMA_VERSION)
        self.assertEqual(doc["generator_version"], GENERATOR_VERSION)
        for entry in doc["issues"]:
            self.assertEqual(entry["schema_version"], SCHEMA_VERSION)
            self.assertEqual(entry["generator_version"], GENERATOR_VERSION)

    def test_atomic_writes(self) -> None:
        target = self.tmp / "nested" / "file.json"
        atomic_write_text(target, '{"ok": true}\n')
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), '{"ok": true}\n')
        leftovers = list(target.parent.glob(".file.json.*.tmp"))
        self.assertEqual(leftovers, [])

    def test_output_containment(self) -> None:
        out = self.tmp / "generated"
        out.mkdir()
        with self.assertRaises(OutputContainmentError):
            ensure_within(out, out.parent / "escape.json")

    def test_output_root_rejects_tldr_directories(self) -> None:
        repo = self.tmp / "repo"
        (repo / "TLDR").mkdir(parents=True)
        (repo / "TLDR AI").mkdir(parents=True)
        with self.assertRaises(OutputContainmentError):
            validate_output_root(repo, repo / "TLDR" / "generated")
        with self.assertRaises(OutputContainmentError):
            validate_output_root(repo, repo / "TLDR AI" / "generated")
        self.assertFalse((repo / "TLDR" / "generated").exists())
        self.assertFalse((repo / "TLDR AI" / "generated").exists())

    def test_cli_rejects_output_inside_tldr_without_writes(self) -> None:
        code = main(
            [
                "--repo-root",
                str(FIXTURES),
                "--output",
                str(FIXTURES / "TLDR" / "generated"),
                "generate",
                "--source",
                "TLDR/article_15-03-2024.md",
            ]
        )
        self.assertEqual(code, 2)
        self.assertFalse((FIXTURES / "TLDR" / "generated").exists())

    def test_source_immutability(self) -> None:
        path = FIXTURES / "TLDR AI" / "article_16-07-2026.md"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        source = resolve_source(FIXTURES, "TLDR AI/article_16-07-2026.md")
        issue = parse_source(source, source.path.read_text(encoding="utf-8"))
        write_issue(self.tmp / "generated", source, issue)
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_per_file_failure_isolation(self) -> None:
        out = self.tmp / "generated"
        boom = "TLDR Crypto/article_01-01-2024.md"

        real_parse = parse_source

        def flaky_parse(source, text):
            if source.relative_path == boom:
                raise RuntimeError("controlled failure")
            return real_parse(source, text)

        with mock.patch("tools.tldr_derive.cli.parse_source", side_effect=flaky_parse):
            code = main(
                [
                    "--repo-root",
                    str(FIXTURES),
                    "--output",
                    str(out),
                    "generate",
                    "--all",
                ]
            )
        self.assertEqual(code, 1)
        good = out / "issues" / "tldr" / "2024" / "2024-03-15.json"
        self.assertTrue(good.exists())
        doc = json.loads(good.read_text(encoding="utf-8"))
        self.assertEqual(doc["parse_status"], "complete")
        # --all with failures must not replace/create a partial full manifest.
        self.assertFalse((out / "manifest.json").exists())
        self.assertFalse((out / "issues" / "tldr-crypto" / "2024" / "2024-01-01.json").exists())

    def test_all_failure_preserves_existing_manifest(self) -> None:
        out = self.tmp / "generated"
        self._generate_all(out)
        before = (out / "manifest.json").read_text(encoding="utf-8")
        prior_count = len(json.loads(before)["issues"])

        def always_fail(source, text):
            raise RuntimeError("boom")

        with mock.patch("tools.tldr_derive.cli.parse_source", side_effect=always_fail):
            code = main(
                [
                    "--repo-root",
                    str(FIXTURES),
                    "--output",
                    str(out),
                    "generate",
                    "--all",
                ]
            )
        self.assertEqual(code, 1)
        after = (out / "manifest.json").read_text(encoding="utf-8")
        self.assertEqual(before, after)
        self.assertEqual(len(json.loads(after)["issues"]), prior_count)

    def test_changed_merges_success_and_keeps_failed_eligible(self) -> None:
        out = self.tmp / "generated"
        sources = self._generate_all(out)
        # Force all to look changed via generator version.
        entries = load_manifest_entries_by_source(out)
        for entry in entries.values():
            entry["generator_version"] = "0.0.0"
        write_manifest(out, list(entries.values()), merge_existing=False)

        boom = sources[0].relative_path
        real_parse = parse_source

        def flaky_parse(source, text):
            if source.relative_path == boom:
                raise RuntimeError("controlled failure")
            return real_parse(source, text)

        with mock.patch("tools.tldr_derive.cli.parse_source", side_effect=flaky_parse):
            code = main(
                [
                    "--repo-root",
                    str(FIXTURES),
                    "--output",
                    str(out),
                    "generate",
                    "--changed",
                ]
            )
        self.assertEqual(code, 1)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        by_src = {e["source_path"]: e for e in manifest["issues"]}
        # Failed source remains old version => still eligible for retry.
        self.assertEqual(by_src[boom]["generator_version"], "0.0.0")
        # Successful updates merged to current generator version.
        success = [e for s, e in by_src.items() if s != boom]
        self.assertTrue(success)
        self.assertTrue(all(e["generator_version"] == GENERATOR_VERSION for e in success))
        retry = filter_changed(sources, out)
        self.assertEqual([s.relative_path for s in retry], [boom])


class CliSmokeTests(unittest.TestCase):
    def test_module_inspect(self) -> None:
        code = main(["--repo-root", str(FIXTURES), "inspect"])
        self.assertEqual(code, 0)

    def test_validate_uses_processed_count(self) -> None:
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--repo-root", str(FIXTURES), "validate", "--all"])
        self.assertEqual(code, 0)
        doc = json.loads(buf.getvalue())
        self.assertIn("processed_count", doc)
        self.assertNotIn("ok_count", doc)
        self.assertEqual(doc["processed_count"], doc["source_count"])
        self.assertIn("warning_code_counts", doc)


if __name__ == "__main__":
    unittest.main()

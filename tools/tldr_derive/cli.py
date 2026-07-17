"""Command-line interface for tools.tldr_derive."""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from typing import Optional

from .discovery import (
    discover_sources,
    resolve_source,
)
from .models import dumps_canonical
from .parser import parse_source
from .validation import validate_sources
from .writer import (
    OutputContainmentError,
    build_manifest_entries,
    filter_changed,
    validate_output_root,
    write_issue,
    write_manifest,
)


def _repo_root_from_args(args: argparse.Namespace) -> Path:
    return Path(args.repo_root).resolve()


def _output_root_from_args(args: argparse.Namespace, repo_root: Path) -> Path:
    return validate_output_root(repo_root, Path(args.output))


def cmd_inspect(args: argparse.Namespace) -> int:
    root = _repo_root_from_args(args)
    sources = discover_sources(root)
    sectors: dict[str, int] = {}
    for source in sources:
        sectors[source.sector] = sectors.get(source.sector, 0) + 1
    doc = {
        "repo_root": str(root),
        "issue_count": len(sources),
        "sectors": [
            {"sector": k, "count": sectors[k]}
            for k in sorted(sectors, key=lambda s: s.lower())
        ],
        "date_min": None,
        "date_max": None,
    }
    if sources:
        dates = sorted(s.date_iso for s in sources)
        doc["date_min"] = dates[0]
        doc["date_max"] = dates[-1]
    sys.stdout.write(dumps_canonical(doc))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    root = _repo_root_from_args(args)
    sources = discover_sources(root)
    if args.source:
        sources = [resolve_source(root, args.source)]
    report = validate_sources(root, sources=sources)
    sys.stdout.write(dumps_canonical(report.to_dict()))
    if report.error_count:
        return 2
    if report.privacy_hits and args.strict_privacy:
        return 3
    return 0


def _select_sources(args: argparse.Namespace, root: Path, output_root: Path):
    if args.source:
        return [resolve_source(root, args.source)]
    sources = discover_sources(root)
    if getattr(args, "changed", False):
        return filter_changed(sources, output_root)
    return sources


def cmd_generate(args: argparse.Namespace) -> int:
    root = _repo_root_from_args(args)
    try:
        output_root = _output_root_from_args(args, root)
    except OutputContainmentError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    dry_run = bool(args.dry_run)
    replace_all = bool(getattr(args, "all", False)) and not args.source
    sources = _select_sources(args, root, output_root)

    issues = []
    failures = []
    written = 0
    skipped = 0

    for source in sources:
        try:
            text = source.path.read_text(encoding="utf-8")
            issue = parse_source(source, text)
            path, _payload = write_issue(
                output_root, source, issue, dry_run=dry_run
            )
            issues.append(issue)
            written += 1
            if args.verbose:
                action = "dry-run" if dry_run else "wrote"
                print(
                    f"{action} {path} status={issue.parse_status} "
                    f"family={issue.format_family}",
                    file=sys.stderr,
                )
        except Exception as exc:  # noqa: BLE001 - isolate per-source failures
            failures.append(
                {
                    "source_path": source.relative_path,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
            )

    entries = build_manifest_entries(issues)
    manifest_written = False
    if issues:
        if replace_all and failures:
            # Do not replace a complete manifest with a partial --all result.
            # Successful issue JSON files already written are preserved.
            manifest_written = False
        elif replace_all:
            write_manifest(
                output_root,
                entries,
                dry_run=dry_run,
                merge_existing=False,
            )
            manifest_written = not dry_run
        else:
            # --changed / --source: merge only successful updates.
            write_manifest(
                output_root,
                entries,
                dry_run=dry_run,
                merge_existing=True,
            )
            manifest_written = not dry_run
    elif replace_all and not failures and not dry_run:
        # Empty successful --all still writes an empty manifest.
        write_manifest(
            output_root,
            [],
            dry_run=False,
            merge_existing=False,
        )
        manifest_written = True

    summary = {
        "dry_run": dry_run,
        "selected": len(sources),
        "written": written,
        "skipped": skipped,
        "failures": failures,
        "manifest_written": manifest_written,
        "manifest_replaced": bool(replace_all and manifest_written and not failures),
        "output": str(output_root),
    }
    sys.stdout.write(dumps_canonical(summary))
    return 1 if failures else 0


def cmd_estimate(args: argparse.Namespace) -> int:
    root = _repo_root_from_args(args)
    sources = discover_sources(root)
    if args.source:
        sources = [resolve_source(root, args.source)]

    sizes: list[int] = []
    status_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}

    for source in sources:
        text = source.path.read_text(encoding="utf-8")
        issue = parse_source(source, text)
        payload = issue.to_dict()
        encoded = dumps_canonical(payload).encode("utf-8")
        sizes.append(len(encoded))
        status_counts[issue.parse_status] = status_counts.get(issue.parse_status, 0) + 1
        family_counts[issue.format_family] = (
            family_counts.get(issue.format_family, 0) + 1
        )

    sizes_sorted = sorted(sizes)
    total = sum(sizes)
    count = len(sizes)
    avg = (total / count) if count else 0.0
    median = float(statistics.median(sizes_sorted)) if sizes_sorted else 0.0
    if sizes_sorted:
        p95_index = min(len(sizes_sorted) - 1, int(len(sizes_sorted) * 0.95))
        p95 = float(sizes_sorted[p95_index])
        maximum = float(sizes_sorted[-1])
    else:
        p95 = 0.0
        maximum = 0.0

    manifest_size = 80 + count * 260
    recent = [s for s in sources if s.date_iso >= "2025-07-17"]
    if not recent:
        recent = sources[-min(365, count) :] if count else []
    if count and recent:
        recent_bytes = int(avg * len(recent))
    elif count:
        recent_bytes = int(avg * min(365, count))
    else:
        recent_bytes = 0

    doc = {
        "issue_count": count,
        "estimated_total_json_bytes": total,
        "average_bytes_per_issue": avg,
        "median_bytes_per_issue": median,
        "p95_bytes_per_issue": p95,
        "max_bytes_per_issue": maximum,
        "estimated_manifest_size_bytes": manifest_size,
        "estimated_annual_repository_growth_bytes": recent_bytes + int(
            (manifest_size / max(count, 1)) * len(recent)
        ),
        "parse_status_counts": dict(sorted(status_counts.items())),
        "format_family_counts": dict(sorted(family_counts.items())),
    }
    sys.stdout.write(dumps_canonical(doc))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m tools.tldr_derive",
        description="Derive normalized TLDR issue JSON from local Markdown sources.",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root containing TLDR* directories (default: .)",
    )
    parser.add_argument(
        "--output",
        default="generated",
        help="Output directory for derived artifacts (default: generated)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="Summarize discoverable sources")
    p_inspect.set_defaults(func=cmd_inspect)

    p_validate = sub.add_parser(
        "validate",
        help=(
            "Parse all/selected sources without writing. "
            "processed_count means parsed without exception, not parse_status=complete."
        ),
    )
    p_validate.add_argument("--all", action="store_true", help="Validate all sources")
    p_validate.add_argument("--source", help="Validate a single source path")
    p_validate.add_argument(
        "--strict-privacy",
        action="store_true",
        help="Exit non-zero if privacy hints are found in derived structures",
    )
    p_validate.set_defaults(func=cmd_validate)

    p_gen = sub.add_parser("generate", help="Generate derived JSON artifacts")
    mode = p_gen.add_mutually_exclusive_group(required=True)
    mode.add_argument("--all", action="store_true", help="Generate all sources")
    mode.add_argument(
        "--changed",
        action="store_true",
        help=(
            "Generate sources whose hash changed, derived JSON is missing, "
            "or schema/generator version differs"
        ),
    )
    mode.add_argument("--source", help="Generate a single source path")
    p_gen.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute outputs without writing files",
    )
    p_gen.add_argument(
        "--output",
        dest="output",
        default=argparse.SUPPRESS,
        help="Output directory (overrides top-level --output)",
    )
    p_gen.set_defaults(func=cmd_generate)

    p_est = sub.add_parser("estimate", help="Estimate derived output sizes")
    p_est.add_argument("--all", action="store_true", help="Estimate all sources")
    p_est.add_argument("--source", help="Estimate a single source path")
    p_est.set_defaults(func=cmd_estimate)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in {"validate", "estimate"} and not args.source:
        args.all = True
    return int(args.func(args))

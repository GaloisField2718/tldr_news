"""Deterministic candidate construction from normalized generated issue JSON."""
from __future__ import annotations
import json
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from .core import EditorialError, SECTOR_ORDER, canonical_bytes

TRACKING = {"utm_source","utm_medium","utm_campaign","utm_term","utm_content","mc_cid","mc_eid"}
CLASS_RANK = {"editorial": 0, "resource": 1, "sponsor": 2}
# Controlled Daily presentation mapping. Corpus values are currently exactly:
# editorial, sponsor, github_repo, tool, and course.
RESOURCE_CONTENT_TYPES = {"github_repo", "course", "tool"}
# Explicit backward-compatible normalized aliases; these are not currently in
# the corpus and remain resource-only if introduced by the normalizer.
RESOURCE_ALIASES = {"resource", "library", "tutorial", "job"}

@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    issue_id: str
    article_id: str
    sector_slug: str
    section_heading: str
    title: str
    summary: str
    canonical_url: str
    source_domain: str
    reading_time: int | None
    content_class: str
    article_order: tuple[int, int]

    @property
    def front_page_eligible(self) -> bool:
        return self.content_class == "editorial" and bool(self.title.strip() and self.summary.strip())

    def dossier(self) -> dict:
        return {"candidate_id":self.candidate_id,"sector_slug":self.sector_slug,"section_heading":self.section_heading,
                "title":self.title,"summary":self.summary,"source_domain":self.source_domain,
                "reading_time":self.reading_time,"content_class":self.content_class}


def sector_key(slug: str) -> tuple[int, str]:
    try: return (SECTOR_ORDER.index(slug), "")
    except ValueError: return (len(SECTOR_ORDER), slug)


def canonicalize_url(url: str) -> str:
    try: p = urlsplit(url.strip())
    except ValueError as exc: raise EditorialError("invalid_article_url") from exc
    if p.scheme.lower() not in ("http", "https") or not p.hostname or p.username or p.password:
        raise EditorialError("invalid_article_url")
    host = p.hostname.lower()
    if p.port and not ((p.scheme.lower()=="http" and p.port==80) or (p.scheme.lower()=="https" and p.port==443)):
        host += f":{p.port}"
    query = urlencode(sorted((k,v) for k,v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in TRACKING), doseq=True)
    return urlunsplit((p.scheme.lower(), host, p.path or "/", query, ""))


def _classification(article: dict) -> str:
    if article.get("is_sponsor") or str(article.get("content_type","")).lower() == "sponsor": return "sponsor"
    if str(article.get("content_type","")).lower() in RESOURCE_CONTENT_TYPES | RESOURCE_ALIASES: return "resource"
    return "editorial"


def load_date(generated: Path, date: str) -> list[Candidate]:
    manifest_path = generated / "manifest.json"
    try: manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise EditorialError("normalized_manifest_invalid") from exc
    pair: dict[tuple[str,str], Candidate] = {}
    for entry in manifest.get("issues", []):
        if entry.get("date") != date or entry.get("parse_status") == "failed": continue
        rel = entry.get("derived_path")
        if not isinstance(rel,str) or ".." in rel.split("/") or not rel.startswith("issues/"): raise EditorialError("normalized_path_invalid")
        try: issue = json.loads((generated/rel).read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError) as exc: raise EditorialError("normalized_issue_invalid") from exc
        if issue.get("date") != date or issue.get("issue_id") != entry.get("issue_id") or issue.get("parse_status") == "failed":
            raise EditorialError("normalized_issue_mismatch")
        for si, section in enumerate(issue.get("sections", [])):
            for ai, article in enumerate(section.get("articles", [])):
                title = article.get("title")
                aid = article.get("id")
                if not isinstance(title,str) or not title.strip() or not isinstance(aid,str) or not aid: continue
                try: url=canonicalize_url(str(article.get("url","")))
                except EditorialError: continue
                klass=_classification(article); key=(issue["issue_id"],aid)
                c=Candidate("", key[0],key[1],str(issue.get("sector_slug","unknown")),str(section.get("heading","")),title.strip(),
                    str(article.get("summary","")).strip(),url,str(article.get("source_domain") or urlsplit(url).hostname or "").lower(),
                    article.get("reading_time_minutes") if isinstance(article.get("reading_time_minutes"),int) else None,klass,(si,ai))
                old=pair.get(key)
                if old is None or CLASS_RANK[klass] > CLASS_RANK[old.content_class]: pair[key]=c
    ordered=sorted(pair.values(), key=lambda c:(sector_key(c.sector_slug),c.article_order,c.issue_id,c.article_id))
    # Canonical URL dedup is scoped by presentation class.
    seen=set(); dedup=[]
    for c in ordered:
        k=(c.content_class,c.canonical_url)
        if k not in seen: seen.add(k); dedup.append(c)
    return dedup


def latest_date(generated: Path) -> str:
    try: entries=json.loads((generated/"manifest.json").read_text(encoding="utf-8"))["issues"]
    except Exception as exc: raise EditorialError("normalized_manifest_invalid") from exc
    dates=[x.get("date") for x in entries if x.get("parse_status") != "failed" and isinstance(x.get("date"),str)]
    if not dates: raise EditorialError("no_complete_issue_dates")
    return max(dates)


def shortlist(candidates: list[Candidate], cap: int) -> list[Candidate]:
    groups: dict[str,list[Candidate]]={}
    for c in candidates: groups.setdefault(c.sector_slug,[]).append(c)
    sectors=sorted(groups,key=sector_key); out=[]
    # Round-robin gives each available sector representation while TLDR wins ties.
    i=0
    while len(out)<cap:
        added=False
        for sector in sectors:
            if i<len(groups[sector]) and len(out)<cap: out.append(groups[sector][i]); added=True
        if not added: break
        i+=1
    return [replace(c,candidate_id=f"c{i:03d}") for i,c in enumerate(out,1)]


def dossier(candidates: list[Candidate]) -> list[dict]: return [c.dossier() for c in candidates]
def dossier_size(candidates: list[Candidate]) -> int: return len(canonical_bytes(dossier(candidates)))

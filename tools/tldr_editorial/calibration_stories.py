"""Immutable calibration-only cross-story visual briefs."""
from __future__ import annotations
import hashlib,json
from dataclasses import dataclass
from types import MappingProxyType
from pathlib import Path
from typing import Mapping
from .candidates import Candidate,load_date
from .core import EditorialError

STORY_SCHEMA_VERSION="1.0.0"
@dataclass(frozen=True)
class CalibrationStory:
 story_id:str;date:str;issue_id:str;article_id:str;expected_title:str;expected_summary_sha256:str
 central_subject:str;visual_metaphor:str;composition:str;forbidden_elements:tuple[str,...];factual_rationale:str;schema_version:str=STORY_SCHEMA_VERSION

_REGISTERED=(
 CalibrationStory("secure-agent-sandboxes-v1","2026-07-16","tldr-ai:2026-07-16","tldr-ai:2026-07-16:a09","SECURE SANDBOXES FOR AGENTS","sha256:5c2ecf066fd4aa84da6ab56c002dc0c4c5be06f4eb031a19c3f5ed8b3b3e9d94","A protected unit of work moving through an ephemeral layered enclosure.","Nested or adjacent temporary compartments isolate execution, control, and secrets while still allowing one controlled task path.","Use an asymmetrical sectional or layered composition. Show separation, controlled passage, and temporary containment without literal cybersecurity icons.",("heroic computer or server","robot or humanoid agent","giant padlock","shield icon","cloud icon","floating UI","code text","hacker imagery","neon cyberpunk","prison cell","permanent fortress","generic circuit decoration","visible labels or arrows"),"SPACE uses temporary sandboxes and separate control and credential layers for sensitive agent tasks."),
 CalibrationStory("workers-automation-threshold-v1","2026-07-16","tldr:2026-07-16","tldr:2026-07-16:a11","THE FIGHT OVER HUMANOID ROBOTS HAS SHUT DOWN A CAR FACTORY FOR THE FIRST TIME","sha256:c90c75a05e5ae63335eea4e9515ab709e96a8c75b78d39655c85d7c74932f51a","A temporarily interrupted industrial line shared between human labor and an incoming automated production structure.","A production path reaches a contested transition point. Human collective presence occupies one side while automation enters its future continuation.","Use lateral tension, interruption, spacing, or an unfinished transition. Humans appear as a collective; automation is emerging industrial capability, not a monster.",("giant threatening robot","robot fighting a worker","literal human-versus-robot split screen","protest fist cliché","handshake cliché","violence","strike placards or visible text","company logos","branded cars or robots","dystopian apocalypse","glowing red robot eyes","triumphant automation advertisement","generic factory stock scene"),"Hyundai workers struck over planned humanoid-robot deployment and job security, creating an organizational threshold rather than a simple human-versus-machine battle."),
)
STORIES:Mapping[str,CalibrationStory]=MappingProxyType({x.story_id:x for x in _REGISTERED})
if len(STORIES)!=len(_REGISTERED):raise RuntimeError("duplicate_calibration_story")
def get_story(story_id:str)->CalibrationStory:
 try:return STORIES[story_id]
 except KeyError as exc:raise KeyError("unknown_calibration_story") from exc

def resolve_story(story:CalibrationStory,generated:Path)->Candidate:
 try:entries=json.loads((generated/"manifest.json").read_text())["issues"]
 except (OSError,json.JSONDecodeError,KeyError,TypeError) as exc:raise EditorialError("calibration_story_manifest_invalid") from exc
 entries=[x for x in entries if x.get("date")==story.date and x.get("issue_id")==story.issue_id]
 if len(entries)!=1 or entries[0].get("parse_status")!="complete":raise EditorialError("calibration_story_issue_incomplete")
 candidates=[c for c in load_date(generated,story.date) if (c.issue_id,c.article_id)==(story.issue_id,story.article_id)]
 if len(candidates)!=1:raise EditorialError("calibration_story_reference_invalid")
 candidate=candidates[0]
 if candidate.content_class!="editorial":raise EditorialError("calibration_story_not_editorial")
 if candidate.title!=story.expected_title:raise EditorialError("calibration_story_title_drift")
 digest="sha256:"+hashlib.sha256(candidate.summary.encode()).hexdigest()
 if digest!=story.expected_summary_sha256:raise EditorialError("calibration_story_summary_drift")
 return candidate

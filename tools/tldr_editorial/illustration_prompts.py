"""Immutable, versioned illustration prompt profiles.

Production intentionally remains pinned to ``baseline-v1``. Profile registration is
data-driven; calibration code does not know or special-case the registered IDs.
"""
from __future__ import annotations
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

PROFILE_SCHEMA_VERSION="1.0.0"
SHARED_FACTUAL_RESTRICTIONS=(
 "Do not render visible text, captions, headlines, or newspaper typography.",
 "Do not render logos or trademarks.",
 "Do not fabricate visible factual evidence.",
 "Do not render interfaces or screenshots.",
 "Do not imitate a named or living artist.",
)

@dataclass(frozen=True)
class PromptProfile:
 profile_id:str
 internal_id:str
 preamble:str
 fixed_negative_constraints:tuple[str,...]
 rendering_material_constraints:tuple[str,...]
 shared_factual_restrictions:tuple[str,...]=SHARED_FACTUAL_RESTRICTIONS
 schema_version:str=PROFILE_SCHEMA_VERSION

# Byte-for-byte legacy production preamble. Do not edit without the later
# production-profile selection and prompt-version migration.
BASELINE_PREAMBLE="""Create a premium editorial illustration for a serious technology newspaper.

The image is an editorial illustration, not documentary photography.
Use one immediately readable focal subject.
Use a strong, restrained composition with controlled contrast.
Use sophisticated but understandable visual symbolism.
Leave useful negative space around the focal subject.
Do not render words, captions, headlines, logos, trademarks, interfaces, screenshots, charts, watermarks, or newspaper typography.
Do not fabricate visible factual evidence.
Do not imitate a named or living illustrator.
Do not create a collage of unrelated news stories.
The image must remain readable at newspaper-column and social-card sizes."""

def _preamble(direction:tuple[str,...],negative:tuple[str,...],materials:tuple[str,...]=())->str:
 sections=["Create an authored editorial illustration for a serious technology newspaper.","","Direction:"]
 sections.extend(f"- {x}" for x in direction)
 if materials:sections.extend(("","Rendering and material constraints:",*(f"- {x}" for x in materials)))
 sections.extend(("","Fixed factual and safety restrictions:",*(f"- {x}" for x in SHARED_FACTUAL_RESTRICTIONS),"","Profile-specific exclusions:",*(f"- {x}" for x in negative)))
 return "\n".join(sections)

def _profile(profile_id:str,internal_id:str,direction:tuple[str,...],negative:tuple[str,...],materials:tuple[str,...]=())->PromptProfile:
 return PromptProfile(profile_id,internal_id,_preamble(direction,negative,materials),negative,materials)

_REGISTERED=(
 PromptProfile("baseline-v1","profile-001",BASELINE_PREAMBLE,("not documentary photography","no collage of unrelated news stories"),()),
 _profile("production-v2","profile-007",(
  "authored editorial print language","deliberate simplified shapes with clear focal hierarchy","restrained limited palette","subtle physical print texture","controlled abstraction and strong negative space","non-photorealistic but factually grounded representation","newspaper and social-card readability"),(
  "glossy CGI","luxury product render","generic futuristic concept art","cyberpunk or neon","glowing circuit-board decoration","floating particles","heroic centered hardware","server rack treated as monument or skyscraper","generic server room","advertising composition","airbrushed gradients","synthetic chrome","excessive pseudo-technical detail","malformed or visible text","labels","diagrams with words")),
 _profile("print-graphic-v1","profile-002",(
  "serious newspaper print illustration","flat, deliberate shapes","restricted palette of approximately three to five colors","subtle paper grain","screen-print or relief-print material character","simplified but accurate geometry","visible authored decisions","no photorealism"),(
  "glossy 3D rendering","neon glows","blue/orange cinematic gradients","translucent holographic layers","floating particles","circuit-board decoration","volumetric light","synthetic chrome","generic futuristic environments","excessive detail")),
 _profile("object-study-v1","profile-003",(
  "one precise editorial object study","physically plausible materials and proportions","calm neutral lighting","restrained background","emphasis on silhouette, scale, construction, and industrial presence","visual interest through framing rather than fantasy symbolism"),(
  "advertising render","product-launch CGI","impossible machinery","dramatic science-fiction scenery","decorative cables or components unsupported by the story","glowing components")),
 _profile("constructed-collage-v1","profile-004",(
  "visibly constructed paper editorial collage","cut-paper shapes","limited physical depth","tactile edges","restrained shadows","simplified symbolic relationships","analogue composition rather than digital photomontage"),(
  "glossy digital collage","surreal accumulation of unrelated objects","floating UI","stock-photo montage","pseudo-3D layers","dense visual clutter")),
 _profile("ink-gouache-v1","profile-005",(
  "ink drawing and opaque gouache","visible brush and line variation","reduced forms","deliberate imperfections","controlled hand-rendered texture","a small number of strong masses","clear newspaper reproduction at reduced size"),(
  "polished concept art","photorealism","airbrushed gradients","digital fantasy lighting","hyper-detailed backgrounds","smooth synthetic surfaces")),
 _profile("cinematic-editorial-v1","profile-006",(
  "controlled cinematic editorial illustration","realistic or strongly stylized rendering permitted","detailed environments permitted when they support the story","dramatic framing and atmosphere permitted","coherent spatial construction","restrained visual narrative tied directly to source facts","strong focal hierarchy despite environmental detail"),(
  "generic cyberpunk imagery","gratuitous neon","floating particles used as decoration","glowing circuit-board motifs","monumental symbolism unrelated to the article","incoherent machinery or architecture","visual overload that obscures the central subject","polished game-concept-art clichés without editorial meaning")),
)
if len({p.profile_id for p in _REGISTERED})!=len(_REGISTERED) or len({p.internal_id for p in _REGISTERED})!=len(_REGISTERED):raise RuntimeError("duplicate_prompt_profile")
PROMPT_PROFILES:Mapping[str,PromptProfile]=MappingProxyType({p.profile_id:p for p in _REGISTERED})
BASELINE_PROFILE=PROMPT_PROFILES["baseline-v1"]

def get_profile(profile_id:str)->PromptProfile:
 try:return PROMPT_PROFILES[profile_id]
 except KeyError as exc:raise KeyError("unknown_prompt_profile") from exc

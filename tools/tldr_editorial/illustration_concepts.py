"""Immutable experimental editorial concepts, independent of rendering style."""
from __future__ import annotations
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

CONCEPT_SCHEMA_VERSION="1.0.0"
HELIOS_SOURCE_REFERENCES=(("tldr:2026-07-21","tldr:2026-07-21:a09"),)

@dataclass(frozen=True)
class ConceptProfile:
 concept_id:str
 central_subject_override:str
 visual_metaphor_override:str
 composition_override:str
 forbidden_elements:tuple[str,...]
 factual_rationale:str
 required_source_references:tuple[tuple[str,str],...]=()
 schema_version:str=CONCEPT_SCHEMA_VERSION

_REGISTERED=(
 ConceptProfile("integrated-stack-v1","Several distinct structural modules becoming one coherent physical system","Separate GPUs, CPUs, networking, and software layers converge into one integrated rack-scale system","Asymmetrical assembly or convergence; separate layers must visibly become one system",("one isolated centered rack","skyscraper metaphor","upward arrow","generic server room","decorative circuit patterns","unrelated floating components"),"AMD is combining GPUs, CPUs, networking, and software into one rack-scale system; integration is the editorial point, not a heroic rack.",HELIOS_SOURCE_REFERENCES),
 ConceptProfile("challenger-enters-v1","A smaller but substantial engineered structure entering a field dominated by a larger established mass","An alternative engineered system creates tension within an established field without depicting literal conflict","Use scale, spacing, tension, or opposing forms; keep the smaller structure credible and materially substantial",("literal David-and-Goliath imagery","logos","mascots","chess pieces","boxing","weapons","two generic glowing towers","combat clichés","upward growth arrows","triumphant advertising composition"),"AMD has a relatively small data-center GPU position and is making a large rack-scale move against the dominant incumbent.",HELIOS_SOURCE_REFERENCES),
 ConceptProfile("system-to-buyer-v1","A constructed rack-scale system in a directional relationship with receiving infrastructure","A system moves from construction into deployment or adoption","Connect system and destination asymmetrically without labels, UI, logos, or literal branded buildings",("handshake imagery","shipping-box clichés","arrows with labels","logos","centered product render","generic cloud icons"),"The significance includes Microsoft being announced as the first customer, so delivery and adoption matter alongside invention.",HELIOS_SOURCE_REFERENCES),
 ConceptProfile("industrial-scale-v1","A modular rack-scale system understood as physical industrial infrastructure","Density, assembly, repetition, and human-relative scale distinguish infrastructure from a chip or consumer product","Use repetition, sectional structure, framing, or scale cues; any rack must belong to a broader industrial system",("isolated rack on an empty background","luxury product photography","impossible machinery","science-fiction server chamber","decorative cables","glowing circuitry"),"Helios is a rack-scale industrial system rather than an individual chip or consumer product.",HELIOS_SOURCE_REFERENCES),
 ConceptProfile("architecture-rivalry-v1","Two distinct engineered system architectures occupying the same field","Different structural logics contrast through construction and organization rather than literal combat","Use parallel, interlocking, diverging, or opposing engineered forms without identifiable branded hardware",("boxing or battle imagery","chessboards","versus symbols","red-versus-green color coding","generic twin towers","explosions","dramatic combat lighting","logos"),"AMD is presenting an alternative integrated architecture intended to compete with Nvidia rack-scale systems.",HELIOS_SOURCE_REFERENCES),
 ConceptProfile("small-share-large-ambition-v1","A small initial engineered footprint developing into a larger credible infrastructure commitment","Spatial proportion contrasts present position with infrastructure-level ambition without magical transformation","Use proportion and spatial contrast without charts, diagrams, numbers, arrows, or exaggerated success symbolism",("charts","percentage graphics","arrows","magical growth","tiny object becoming a skyscraper","exaggerated success symbolism"),"AMD currently has a small data-center GPU share while making a large infrastructure-level commitment.",HELIOS_SOURCE_REFERENCES),
)
if len({x.concept_id for x in _REGISTERED})!=len(_REGISTERED):raise RuntimeError("duplicate_concept_profile")
CONCEPT_PROFILES:Mapping[str,ConceptProfile]=MappingProxyType({x.concept_id:x for x in _REGISTERED})

def get_concept(concept_id:str)->ConceptProfile:
 try:return CONCEPT_PROFILES[concept_id]
 except KeyError as exc:raise KeyError("unknown_concept_profile") from exc

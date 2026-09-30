from typing import Dict, List, Optional, Tuple
from src.domain.models import Smell, TradeOff, QualityAttribute

Security = QualityAttribute.SECURITY
Performance = QualityAttribute.PERFORMANCE
Maintainability = QualityAttribute.MAINTAINABILITY
Reproducibility = QualityAttribute.REPRODUCIBILITY

# Human-authored explanations for the smells whose impact scores in
# config/smell_impacts.yaml mix a positive and a negative attribute. Keyed first by
# smell concept and then by (positive, negative) attribute pair: a pair-only lookup
# would collide two unrelated smells that happen to trade the same two attributes
# (e.g. ADD-vs-COPY and platform pinning both trade Maintainability for
# Reproducibility in opposite directions), attaching the wrong smell's explanation.
_CONCEPT_EXPLANATIONS: Dict[str, Dict[Tuple[QualityAttribute, QualityAttribute], str]] = {
    "ADD_INSTEAD_OF_COPY": {
        (Maintainability, Security): (
            "Using ADD instead of COPY is more convenient (it can fetch URLs and "
            "auto-extract archives), but that same flexibility widens the attack "
            "surface, harming security."
        ),
        (Maintainability, Reproducibility): (
            "ADD's auto-extraction and remote-fetch convenience comes at the cost of "
            "reproducibility: the extracted contents or fetched resource can differ "
            "between builds in ways a plain COPY of a local file never would."
        ),
    },
    "APK_NO_CACHE_MISSING": {
        (Security, Performance): (
            "Disabling apk's cache (--no-cache) forces every install to fetch the "
            "latest package index, improving security by avoiding stale, potentially "
            "vulnerable cached packages, at the cost of slower builds."
        ),
    },
    "IMPRECISE_TAG": {
        (Security, Reproducibility): (
            "Using a floating tag (e.g., 'latest') improves security by allowing "
            "automatic patch updates, but harms reproducibility. Pinning the version "
            "would do the opposite."
        ),
    },
    "PLATFORM_PINNING": {
        (Reproducibility, Maintainability): (
            "Pinning the build to a specific platform (e.g. via --platform) makes the "
            "image fully reproducible for that target, but reduces "
            "maintainability/portability since the Dockerfile can no longer build for "
            "other platforms without editing it."
        ),
    },
}

# Same rule-name substrings src.integrations.parfum.client._get_smell_impacts uses to
# map a raw Parfum rule id to a smell concept, restricted to the concepts above.
_SMELL_NAME_KEYWORDS: Tuple[Tuple[str, str], ...] = (
    ("dl3020", "ADD_INSTEAD_OF_COPY"),
    ("apkaddusecache", "APK_NO_CACHE_MISSING"),
    ("latesttag", "IMPRECISE_TAG"),
    ("dl3029", "PLATFORM_PINNING"),
)


def _smell_concept(smell_name: str) -> Optional[str]:
    name_lower = smell_name.lower()
    for keyword, concept in _SMELL_NAME_KEYWORDS:
        if keyword in name_lower:
            return concept
    return None


def detect_trade_offs(smell: Smell) -> List[TradeOff]:
    trade_offs = []
    positives = [imp for imp in smell.impacts if imp.score > 0]
    negatives = [imp for imp in smell.impacts if imp.score < 0]
    concept = _smell_concept(smell.name)
    concept_explanations = _CONCEPT_EXPLANATIONS.get(concept, {}) if concept else {}

    for pos in positives:
        for neg in negatives:
            explanation = concept_explanations.get(
                (pos.attribute, neg.attribute),
                f"Improves {pos.attribute.value} but reduces {neg.attribute.value}.",
            )
            trade_offs.append(TradeOff(
                positive_impact=pos,
                negative_impact=neg,
                explanation=explanation
            ))
    return trade_offs

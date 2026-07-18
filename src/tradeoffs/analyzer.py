from typing import List
from src.domain.models import Smell, TradeOff, QualityAttribute

def detect_trade_offs(smell: Smell) -> List[TradeOff]:
    trade_offs = []
    positives = [imp for imp in smell.impacts if imp.score > 0]
    negatives = [imp for imp in smell.impacts if imp.score < 0]

    for pos in positives:
        for neg in negatives:
            explanation = f"Improves {pos.attribute.value} but reduces {neg.attribute.value}."

            # Add a more specific explanation for the reproducibility vs. security trade-off
            if (pos.attribute == QualityAttribute.SECURITY and neg.attribute == QualityAttribute.REPRODUCIBILITY) or \
               (pos.attribute == QualityAttribute.REPRODUCIBILITY and neg.attribute == QualityAttribute.SECURITY):
                explanation = "Using a floating tag (e.g., 'latest') improves security by allowing automatic patch updates, but harms reproducibility. Pinning the version would do the opposite."

            trade_offs.append(TradeOff(
                positive_impact=pos,
                negative_impact=neg,
                explanation=explanation
            ))
    return trade_offs

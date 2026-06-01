from typing import List
from src.domain.models import Smell, TradeOff

def detect_trade_offs(smell: Smell) -> List[TradeOff]:
    trade_offs = []
    positives = [imp for imp in smell.impacts if imp.score > 0]
    negatives = [imp for imp in smell.impacts if imp.score < 0]

    for pos in positives:
        for neg in negatives:
            trade_offs.append(TradeOff(
                positive_impact=pos,
                negative_impact=neg,
                explanation=f"Improves {pos.attribute.value} but reduces {neg.attribute.value}."
            ))
    return trade_offs

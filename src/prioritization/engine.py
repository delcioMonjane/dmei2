from typing import List
from src.domain.models import Smell, DeveloperPreferences, PrioritizedRepair
from src.tradeoffs.analyzer import detect_trade_offs

def calculate_score(smell: Smell, prefs: DeveloperPreferences) -> float:
    score = 0.0
    # Create a dictionary for faster lookup
    impact_dict = {imp.attribute.value: imp.score for imp in smell.impacts}

    for qa, weight in prefs.weights.items():
        score += impact_dict.get(qa.value, 0) * weight

    return score

def prioritize_repairs(smells: List[Smell], prefs: DeveloperPreferences) -> List[PrioritizedRepair]:
    prioritized = []
    for smell in smells:
        for repair in smell.available_repairs:
            score = calculate_score(smell, prefs)
            trade_offs = detect_trade_offs(smell)
            prioritized.append(PrioritizedRepair(
                repair=repair, smell=smell, final_score=score, trade_offs=trade_offs
            ))

    # Sort ascending by score (more negative is higher priority)
    return sorted(prioritized, key=lambda x: x.final_score)

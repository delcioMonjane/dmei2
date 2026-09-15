from src.domain.models import Smell, QualityImpact, QualityAttribute, RepairAction, DeveloperPreferences
from src.prioritization.engine import calculate_score, prioritize_repairs

def test_calculate_score():
    # Scores follow the same sign convention as config/smell_impacts.yaml: negative
    # means the smell's presence harms that quality attribute (RUN_AS_ROOT: Security -10).
    smell = Smell(
        smell_id="S-1",
        name="RUN_AS_ROOT",
        line_number=5,
        impacts=[
            QualityImpact(attribute=QualityAttribute.SECURITY, score=-10.0),
            QualityImpact(attribute=QualityAttribute.PERFORMANCE, score=0.0)
        ],
        available_repairs=[]
    )
    prefs = DeveloperPreferences(weights={QualityAttribute.SECURITY: 2.0})
    score = calculate_score(smell, prefs)
    assert score == -20.0

def test_prioritize_repairs():
    smell = Smell(
        smell_id="S-1",
        name="LATEST_TAG_USED",
        line_number=2,
        impacts=[
            QualityImpact(attribute=QualityAttribute.REPRODUCIBILITY, score=10.0),
            QualityImpact(attribute=QualityAttribute.MAINTAINABILITY, score=-2.0)
        ],
        available_repairs=[
            RepairAction(repair_id="R-1", description="Pin tag", diff_patch="")
        ]
    )
    prefs = DeveloperPreferences(weights={QualityAttribute.REPRODUCIBILITY: 1.0, QualityAttribute.MAINTAINABILITY: 1.0})

    prioritized = prioritize_repairs([smell], prefs)

    assert len(prioritized) == 1
    assert prioritized[0].final_score == 8.0
    assert len(prioritized[0].trade_offs) == 1
    assert prioritized[0].trade_offs[0].positive_impact.attribute == QualityAttribute.REPRODUCIBILITY
    assert prioritized[0].trade_offs[0].negative_impact.attribute == QualityAttribute.MAINTAINABILITY

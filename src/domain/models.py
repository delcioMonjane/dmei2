from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from enum import Enum

class QualityAttribute(str, Enum):
    SECURITY = "Security"
    PERFORMANCE = "Performance"
    MAINTAINABILITY = "Maintainability"
    REPRODUCIBILITY = "Reproducibility"

class DeveloperPreferences(BaseModel):
    weights: Dict[QualityAttribute, float] = Field(
        default_factory=lambda: {qa: 1.0 for qa in QualityAttribute}
    )

class QualityImpact(BaseModel):
    attribute: QualityAttribute
    score: float  # -10.0 to 10.0

class TradeOff(BaseModel):
    positive_impact: QualityImpact
    negative_impact: QualityImpact
    explanation: str

class RepairAction(BaseModel):
    repair_id: str
    description: str
    diff_patch: str

class Smell(BaseModel):
    smell_id: str
    name: str
    line_number: int
    impacts: List[QualityImpact] = Field(default_factory=list)
    available_repairs: List[RepairAction] = Field(default_factory=list)

class PrioritizedRepair(BaseModel):
    repair: RepairAction
    smell: Smell
    final_score: float
    trade_offs: List[TradeOff]

class AnalysisResult(BaseModel):
    analysis_id: str
    dockerfile_path: str
    detected_smells: List[Smell]
    prioritized_repairs: List[PrioritizedRepair]

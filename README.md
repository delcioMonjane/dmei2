# A Trade-off-Aware Approach for Prioritized Refactoring of Dockerfiles

This document outlines the complete software architecture and implementation plan for a Python-based CLI tool that serves as a decision-support system for Dockerfile refactoring. It relies on [Parfum](https://github.com/tdurieux/docker-parfum) for smell detection and repair extraction, while contributing a novel trade-off-aware prioritization engine.

---

## 1. System Architecture

The architecture follows a layered design to ensure a clean separation of concerns, built specifically for a CLI execution context.

```text
+-------------------------------------------------------------+
|                        CLI Layer                            |
|  (Typer, Rich: Input handling, Configuration, Formatting)   |
+-------------------------------------------------------------+
               |                              |
+--------------------------+    +-----------------------------+
|    Reporting Layer       |    |     Persistence Layer       |
| (JSON, CSV, MD, Console) |    | (SQLite: Store analyses)    |
+--------------------------+    +-----------------------------+
               |                              |
+-------------------------------------------------------------+
|                    Prioritization Layer                     |
|  (Ranks repairs, Applies dev preferences, Computes scores)  |
+-------------------------------------------------------------+
               |                              |
+--------------------------+    +-----------------------------+
|      Analysis Layer      |    | Trade-off Analysis Layer    |
| (Smell processing, QA    |    | (Detect conflicting QA      |
|  mapping, impact calc)   |    |  attributes, explanations)  |
+--------------------------+    +-----------------------------+
               |
+-------------------------------------------------------------+
|                  Parfum Integration Layer                   |
| (Subprocess execution, Output parsing, Error handling)      |
+-------------------------------------------------------------+
```

### Layer Responsibilities:
*   **CLI Layer:** Uses `Typer` to define CLI commands. Parses flags, loads `PyYAML` configs, and uses `Rich` to render terminal outputs.
*   **Parfum Integration Layer:** Executes the local Parfum installation via Python's `subprocess`. Captures its analysis and proposed repairs, standardizing the payload.
*   **Analysis Layer:** Maps the detected smells to their corresponding Quality Attribute (QA) impacts (Security, Performance, Maintainability, Reproducibility).
*   **Prioritization Layer:** Core research engine. Ingests developer preferences (weights), calculates a global priority score for each repair action using a Weighted Sum Model.
*   **Trade-off Analysis Layer:** Detects instances where a repair positively impacts one QA but negatively impacts another, formatting an explanation.
*   **Persistence Layer:** Uses `SQLite` and `sqlite3` to persist historic analyses, making it possible to query trends over time.
*   **Reporting Layer:** Uses `Pandas` internally to format the prioritization results and export them as JSON, CSV, or Markdown.

---

## 2. Domain Model

The domain model represents the core entities using `Pydantic` for strict validation.

```python
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
    impacts: List[QualityImpact]
    available_repairs: List[RepairAction]

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
```

---

## 3. CLI Design

The application will be accessible via the `docker-prioritizer` CLI.

### `analyze`
*   **Purpose:** Runs Parfum, detects smells, and outputs the raw analysis.
*   **Parameters:** `[FILE_PATH]`
*   **Output:** Rich console table of smells.
*   **Example:** `docker-prioritizer analyze Dockerfile`

### `prioritize`
*   **Purpose:** Takes a Dockerfile (and optionally developer weights) and returns ranked repairs.
*   **Parameters:** `[FILE_PATH] --config weights.yaml`
*   **Output:** Ranked list of repairs with scores and trade-offs.
*   **Example:** `docker-prioritizer prioritize Dockerfile --config prod-weights.yaml`

### `apply`
*   **Purpose:** Applies a specific repair patch to the Dockerfile.
*   **Parameters:** `[FILE_PATH] --repair-id ID`
*   **Output:** Success message.
*   **Example:** `docker-prioritizer apply Dockerfile --repair-id R-123`

### `report`
*   **Purpose:** Fetches a previous analysis from SQLite and exports it.
*   **Parameters:** `[ANALYSIS_ID] --format [json|csv|md]`
*   **Output:** File creation.
*   **Example:** `docker-prioritizer report 5f3a2b --format md`

### `compare`
*   **Purpose:** Compares the QA profile of a Dockerfile before and after applying a repair.
*   **Parameters:** `[BEFORE_FILE] [AFTER_FILE]`
*   **Output:** Delta of Quality Attributes.
*   **Example:** `docker-prioritizer compare Dockerfile Dockerfile.fixed`

---

## 4. Parfum Integration

Python interacts with Parfum by executing it as a subprocess. 

```python
import subprocess
import json
from pathlib import Path
from typing import Dict, Any

class ParfumIntegration:
    def __init__(self, parfum_executable: str = "parfum"):
        self.parfum_executable = parfum_executable

    def analyze(self, dockerfile_path: Path) -> Dict[str, Any]:
        """Executes Parfum and captures the output JSON."""
        try:
            result = subprocess.run(
                [self.parfum_executable, "analyze", "--format", "json", str(dockerfile_path)],
                capture_output=True,
                text=True,
                check=True
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            print(f"Parfum execution failed. Stderr: {e.stderr}")
            raise
        except json.JSONDecodeError:
            print("Failed to parse Parfum output.")
            raise
```

---

## 5. Quality Attribute Model

Smell impacts are decoupled into a configuration file (`smell_impacts.yaml`), loaded during execution.

```yaml
# smell_impacts.yaml
smells:
  "RUN_AS_ROOT":
    Security: 10
    Performance: 0
    Maintainability: 0
    Reproducibility: 0
  "CACHE_NOT_CLEANED":
    Security: 0
    Performance: 9
    Maintainability: 0
    Reproducibility: 0
  "MISSING_VERSION_PINNING":
    Security: 4
    Performance: 0
    Maintainability: 3
    Reproducibility: 9
  "LATEST_TAG_USED":
    Security: 3
    Performance: 0
    Maintainability: -2 # Fixing this forces constant updates
    Reproducibility: 10
```

---

## 6. Prioritization Algorithm

### Mathematical Formulation
The algorithm utilizes a Weighted Sum Model (WSM).
For a given repair $r$ associated with a smell $S$:
$$Score(r) = \sum_{q \in QA} Weight(q) \times Impact(S, q)$$

### Complexity Analysis
*   $N$: Number of smells detected
*   $M$: Number of possible repairs per smell (usually 1-3)
*   $Q$: Number of Quality Attributes (constant, 4)
*   **Time Complexity:** $O(N \times M \times Q)$ which simplifies to $O(N)$. Extremely efficient.

### Python Implementation
```python
def calculate_score(smell: Smell, prefs: DeveloperPreferences) -> float:
    score = 0.0
    for impact in smell.impacts:
        weight = prefs.weights.get(impact.attribute, 1.0)
        score += weight * impact.score
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
    
    # Sort descending by score
    return sorted(prioritized, key=lambda x: x.final_score, reverse=True)
```

---

## 7. Trade-off Analysis

If fixing a smell improves one attribute but degrades another, it's a trade-off.

### Detection Method
```python
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
```

---

## 8. Persistence

SQLite Database designed to store historical runs.

```sql
CREATE TABLE analyses (
    id TEXT PRIMARY KEY,
    dockerfile_path TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE smells (
    id TEXT PRIMARY KEY,
    analysis_id TEXT REFERENCES analyses(id),
    name TEXT NOT NULL,
    line_number INTEGER
);

CREATE TABLE repairs (
    id TEXT PRIMARY KEY,
    smell_id TEXT REFERENCES smells(id),
    description TEXT,
    diff_patch TEXT,
    final_score REAL
);

CREATE TABLE tradeoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repair_id TEXT REFERENCES repairs(id),
    positive_attribute TEXT,
    negative_attribute TEXT,
    explanation TEXT
);
```

---

## 9. Reporting

Using `Rich` for CLI output formatting.

### Console Example Output

```text
Detected 8 smells in Dockerfile

Priority Ranking:
=========================================================
1. Missing Version Pinning (Score: 11.5)
   Repair: Pin 'python' to '3.12-slim'
   Security: +4 | Reproducibility: +9 | Maintainability: -2
   [!] Trade-off: Improves Reproducibility but reduces Maintainability (requires manual updates).

2. Run as root (Score: 10.0)
   Repair: Add 'USER appuser'
   Security: +10 | Performance: 0 | Maintainability: 0
   [!] Trade-off: None
```

---

## 10. Evaluation Methodology

### Dataset Collection
*   **Strategy:** Crawl 500-1000 open-source Dockerfiles from GitHub using GitHub API, filtering for repositories with >100 stars to ensure realistic project complexities.

### Experimental Procedure
*   **RQ1 (Impact):** Run Parfum on the dataset. Extract frequency of smells. Map to QA impacts to identify which software attributes are most commonly degraded in the wild.
*   **RQ2 (Trade-offs & Priorities):** Define 3 developer profiles: "Security First" (Security weight=2.0), "Fast CI/CD" (Performance weight=2.0), "Stable Release" (Reproducibility weight=2.0). Run the prioritization algorithm for each profile and analyze how the top-5 recommended repairs change.
*   **RQ3 (Practical Outcome):** Select a subset of 20 Dockerfiles. Apply the top 3 repairs. Measure build times (Performance) and image vulnerability counts using Trivy (Security) before and after.

---

## 11. Project Structure

```text
docker-prioritizer/
│
├── src/
│   ├── cli/                   # Typer commands (main.py, commands.py)
│   ├── domain/                # Pydantic models (models.py)
│   ├── integrations/
│   │   └── parfum/            # Subprocess wrapper, parser (client.py)
│   ├── prioritization/        # Algorithm (engine.py)
│   ├── tradeoffs/             # Tradeoff detection (analyzer.py)
│   ├── persistence/           # SQLite DB setup and queries (db.py)
│   └── reports/               # Pandas export logic, Rich tables (exporter.py)
│
├── config/                    
│   └── smell_impacts.yaml     # Baseline smell->QA mapping
│
├── datasets/                  # Scripts to fetch GH Dockerfiles
│
├── tests/                     # pytest suite (test_engine.py, test_parser.py)
│
├── pyproject.toml             # Dependencies (typer, pydantic, rich, pandas, pyyaml)
└── README.md
```

---

## 12. Dissertation Alignment

This architecture cleanly defines the boundaries between existing work and the novel dissertation contribution.

### Existing Contribution (Parfum)
*   **Detection:** Parsing the Dockerfile AST and finding issues.
*   **Repair:** Generating AST diffs and text patches.
*   *Role in Architecture:* Isolated entirely in the `integrations/parfum/` layer. It acts strictly as an oracle for smells and patches.

### Novel Contribution (This Dissertation)
*   **Trade-off modelling (`domain/`, `config/`):** A formalized model connecting Dockerfile smells to standard Software Architecture Quality Attributes.
*   **Decision Support (`prioritization/`, `tradeoffs/`):** The WSM algorithm and conflict detection logic that empowers developers to make informed decisions rather than blindly applying patches.
*   **Repair Ranking (`cli/`, `reports/`):** The practical interface that solves the "Which patch first?" problem.

By treating Parfum as a black-box generator of repairs, the dissertation heavily emphasizes the **Software Engineering / Decision Making** contribution (answering RQs 1, 2, and 3), avoiding the trap of simply "building another linter".

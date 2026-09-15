 # Docker Prioritizer

A trade-off-aware command-line tool for **prioritized refactoring of Dockerfiles**.

Linters like [Hadolint](https://github.com/hadolint/hadolint) and repair tools like
[Parfum](https://github.com/tdurieux/docker-parfum) can detect Dockerfile smells and even fix
them automatically, but they treat every smell as equally important. In practice, fixing one
issue can improve one quality attribute while quietly harming another — for example, pinning a
base image version improves **reproducibility** but can reduce **maintainability** by requiring
manual updates.

Docker Prioritizer sits on top of Parfum's detection engine and adds the missing piece: a
**prioritization and trade-off model** that ranks proposed repairs according to their impact on
four quality attributes — Security, Performance, Maintainability and Reproducibility — and the
developer's own preferences, and it explicitly surfaces the trade-offs behind each
recommendation. This project is the prototype implementation built for the MSc dissertation
*"A Trade-off-Aware Approach for Prioritized Refactoring of Dockerfiles"*.

## Features

- **Smell detection** via [Parfum](https://github.com/tdurieux/docker-parfum), used as an
  external detection/repair engine.
- **Trade-off-aware prioritization** using a configurable Weighted Sum Model over four quality
  attributes.
- **Trade-off explanations** — every recommendation states which attributes it improves and
  which it may harm.
- **Automated repair** via Parfum's repair engine.
- **Before/after comparison** of the quality-attribute profile of two Dockerfiles.
- **Persisted analysis history** in a local SQLite database, re-exportable as JSON, CSV or
  Markdown.

## How it works

```text
+-------------------------------------------------------------+
|                        CLI Layer (Typer, Rich)               |
+-------------------------------------------------------------+
               |                              |
+--------------------------+    +-----------------------------+
|    Reporting Layer       |    |     Persistence Layer       |
| (JSON, CSV, MD, Console) |    | (SQLite: stores analyses)   |
+--------------------------+    +-----------------------------+
               |                              |
+-------------------------------------------------------------+
|                    Prioritization Layer                     |
|  (Ranks repairs, applies developer preferences, WSM scores) |
+-------------------------------------------------------------+
               |                              |
+--------------------------+    +-----------------------------+
|      Domain Model        |    | Trade-off Analysis Layer    |
| (Smells, QA impacts)     |    | (Detects conflicting QA     |
|                          |    |  impacts, explanations)     |
+--------------------------+    +-----------------------------+
               |
+-------------------------------------------------------------+
|                  Parfum Integration Layer                   |
| (Subprocess execution, output parsing, error handling)      |
+-------------------------------------------------------------+
```

Each detected smell carries a set of pre-calibrated impact scores on a **-10 (harmful) to +10
(beneficial)** scale per quality attribute, defined in [`config/smell_impacts.yaml`](config/smell_impacts.yaml).
The prioritization engine combines those scores with developer-defined weights into a single
priority score per repair; the trade-off analyzer flags any smell whose impacts point in
opposite directions across attributes.

## Prerequisites

- **Python 3.8+**
- **[Poetry](https://python-poetry.org/)** for dependency management
- **Node.js and npm** (required by Parfum)
- **[Parfum](https://github.com/tdurieux/docker-parfum)**, installed globally:

  ```bash
  npm install -g @tdurieux/docker-parfum
  ```

  Verify it's on your `PATH`:

  ```bash
  docker-parfum --help
  ```

## Installation

```bash
git clone <this-repository-url>
cd dmei2
poetry install
```

`poetry install` registers the `docker-prioritizer` command inside the Poetry-managed
virtual environment. Run commands either via `poetry run docker-prioritizer ...`, or activate
the environment first (`poetry shell`) and call `docker-prioritizer` directly.

Verify the install:

```bash
poetry run docker-prioritizer --help
```

### Configuration

Runtime configuration lives in [`config/settings.yaml`](config/settings.yaml):

```yaml
parfum_executable: "docker-parfum"
database_path: "docker_prioritizer.db"
```

Both values can be overridden without editing the file, using environment variables — useful
for CI, containers, or a local Parfum build that isn't on `PATH`:

| Environment variable | Overrides                | Example |
|-----------------------|---------------------------|---------|
| `PARFUM_EXECUTABLE`   | `parfum_executable`        | `PARFUM_EXECUTABLE="node /path/to/docker-parfum/build/cli/index.js"` |
| `DATABASE_PATH`       | `database_path`             | `DATABASE_PATH="/tmp/docker-prioritizer.db"` |

Smell-to-quality-attribute impact scores are defined in
[`config/smell_impacts.yaml`](config/smell_impacts.yaml) and can be recalibrated without
touching code.

## Usage

```bash
# Detect smells in a Dockerfile
docker-prioritizer analyze Dockerfile

# Detect smells and rank their repairs by priority (default: equal weights)
docker-prioritizer prioritize Dockerfile

# Rank using custom developer preferences (see security-first-weights.yaml for the format)
docker-prioritizer prioritize Dockerfile --config security-first-weights.yaml

# Apply Parfum's automated repairs
docker-prioritizer apply Dockerfile --output Dockerfile.repaired

# Compare the quality-attribute profile of two Dockerfiles
docker-prioritizer compare Dockerfile Dockerfile.repaired

# Re-export a previously stored analysis (the ID is printed by `prioritize`)
docker-prioritizer report <ANALYSIS_ID> --format md --output report.md
```

Example `prioritize` output:

```text
Detected 8 smells in Dockerfile

Priority Ranking:
=========================================================
1. Missing Version Pinning (Score: -11.5)
   Repair: Pin 'python' to '3.12-slim'
   Security: +4 | Reproducibility: -9 | Maintainability: -2
   [!] Trade-off: Improves Security but reduces Reproducibility.

2. Run as root (Score: -10.0)
   Repair: Add 'USER appuser'
   Security: -10 | Performance: 0 | Maintainability: 0
   [!] Trade-off: None
```

Custom weight profiles are plain YAML files:

```yaml
# security-first-weights.yaml
weights:
  Security: 2.0
  Performance: 1.0
  Maintainability: 0.5
  Reproducibility: 1.0
```

## Development

```bash
# Run the test suite
poetry run pytest

# Format code
poetry run black src tests
```

### Project structure

```text
src/
├── cli/                   # Typer commands (main.py)
├── domain/                 # Pydantic domain models (models.py)
├── integrations/
│   └── parfum/              # Subprocess wrapper and output parser (client.py)
├── prioritization/          # Weighted Sum Model prioritization engine
├── tradeoffs/                # Trade-off detection (analyzer.py)
├── persistence/              # SQLite storage (db.py)
└── reports/                  # Console/JSON/CSV/Markdown export (exporter.py)

config/
├── settings.yaml            # Parfum command + database path
└── smell_impacts.yaml       # Smell → quality-attribute impact mapping

evaluation/                  # Scripts used for the dissertation's empirical evaluation
tests/                       # pytest suite
```

## Acknowledgements

Smell detection and automated repair are provided by
[Parfum](https://github.com/tdurieux/docker-parfum) (Durieux et al.). This project treats
Parfum as a black-box oracle for smells and patches, and contributes the trade-off-aware
prioritization model, decision-support reporting, and empirical evaluation on top of it.

import os
import sqlite3
from pathlib import Path
from typing import List, Optional

import yaml

from src.domain.models import (
    AnalysisResult,
    PrioritizedRepair,
    QualityAttribute,
    QualityImpact,
    RepairAction,
    Smell,
    TradeOff,
)

PROJECT_ROOT = Path(__file__).parent.parent.parent


def get_db_path() -> Path:
    """Resolves the SQLite database path: DATABASE_PATH env var, then settings.yaml, then a default."""
    env_override = os.environ.get("DATABASE_PATH")
    if env_override:
        return Path(env_override)

    settings_path = PROJECT_ROOT / "config" / "settings.yaml"
    db_path_str = "docker_prioritizer.db"  # Default fallback
    if settings_path.exists():
        with open(settings_path, "r") as f:
            settings = yaml.safe_load(f) or {}
            db_path_str = settings.get("database_path", db_path_str)

    db_path = Path(db_path_str)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    return db_path


DB_FILE = get_db_path()


def init_db():
    """Initializes the database tables if they don't exist."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                dockerfile_path TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS smells (
                id TEXT PRIMARY KEY,
                analysis_id TEXT REFERENCES analyses(id),
                name TEXT NOT NULL,
                line_number INTEGER
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS smell_impacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                smell_id TEXT REFERENCES smells(id),
                attribute TEXT NOT NULL,
                score REAL NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS repairs (
                id TEXT PRIMARY KEY,
                smell_id TEXT REFERENCES smells(id),
                description TEXT,
                diff_patch TEXT,
                final_score REAL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tradeoffs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repair_id TEXT REFERENCES repairs(id),
                positive_attribute TEXT,
                positive_score REAL,
                negative_attribute TEXT,
                negative_score REAL,
                explanation TEXT
            );
        """)
        conn.commit()


def save_analysis(analysis: AnalysisResult):
    """Saves a complete analysis result to the database."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO analyses (id, dockerfile_path) VALUES (?, ?)",
                       (analysis.analysis_id, analysis.dockerfile_path))

        for smell in analysis.detected_smells:
            cursor.execute("INSERT INTO smells (id, analysis_id, name, line_number) VALUES (?, ?, ?, ?)",
                           (smell.smell_id, analysis.analysis_id, smell.name, smell.line_number))
            for impact in smell.impacts:
                cursor.execute(
                    "INSERT INTO smell_impacts (smell_id, attribute, score) VALUES (?, ?, ?)",
                    (smell.smell_id, impact.attribute.value, impact.score),
                )

        for prio_repair in analysis.prioritized_repairs:
            repair = prio_repair.repair
            smell = prio_repair.smell
            cursor.execute("INSERT INTO repairs (id, smell_id, description, diff_patch, final_score) VALUES (?, ?, ?, ?, ?)",
                           (repair.repair_id, smell.smell_id, repair.description, repair.diff_patch, prio_repair.final_score))

            for tradeoff in prio_repair.trade_offs:
                cursor.execute(
                    "INSERT INTO tradeoffs "
                    "(repair_id, positive_attribute, positive_score, negative_attribute, negative_score, explanation) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        repair.repair_id,
                        tradeoff.positive_impact.attribute.value,
                        tradeoff.positive_impact.score,
                        tradeoff.negative_impact.attribute.value,
                        tradeoff.negative_impact.score,
                        tradeoff.explanation,
                    ),
                )
        conn.commit()


def get_analysis(analysis_id: str) -> Optional[AnalysisResult]:
    """Reconstructs a complete AnalysisResult, including smells, repairs and trade-offs, from storage."""
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT dockerfile_path FROM analyses WHERE id = ?", (analysis_id,))
        analysis_row = cursor.fetchone()
        if not analysis_row:
            return None

        cursor.execute(
            "SELECT id, name, line_number FROM smells WHERE analysis_id = ?", (analysis_id,)
        )
        smell_rows = cursor.fetchall()

        detected_smells: List[Smell] = []
        prioritized_repairs: List[PrioritizedRepair] = []

        for smell_row in smell_rows:
            cursor.execute(
                "SELECT attribute, score FROM smell_impacts WHERE smell_id = ?", (smell_row["id"],)
            )
            impacts = [
                QualityImpact(attribute=QualityAttribute(row["attribute"]), score=row["score"])
                for row in cursor.fetchall()
            ]

            cursor.execute(
                "SELECT id, description, diff_patch, final_score FROM repairs WHERE smell_id = ?",
                (smell_row["id"],),
            )
            repair_rows = cursor.fetchall()

            smell = Smell(
                smell_id=smell_row["id"],
                name=smell_row["name"],
                line_number=smell_row["line_number"],
                impacts=impacts,
                available_repairs=[
                    RepairAction(
                        repair_id=row["id"],
                        description=row["description"],
                        diff_patch=row["diff_patch"] or "",
                    )
                    for row in repair_rows
                ],
            )
            detected_smells.append(smell)

            for repair_row in repair_rows:
                cursor.execute(
                    "SELECT positive_attribute, positive_score, negative_attribute, negative_score, explanation "
                    "FROM tradeoffs WHERE repair_id = ?",
                    (repair_row["id"],),
                )
                trade_offs = [
                    TradeOff(
                        positive_impact=QualityImpact(
                            attribute=QualityAttribute(row["positive_attribute"]), score=row["positive_score"]
                        ),
                        negative_impact=QualityImpact(
                            attribute=QualityAttribute(row["negative_attribute"]), score=row["negative_score"]
                        ),
                        explanation=row["explanation"],
                    )
                    for row in cursor.fetchall()
                ]

                prioritized_repairs.append(
                    PrioritizedRepair(
                        repair=RepairAction(
                            repair_id=repair_row["id"],
                            description=repair_row["description"],
                            diff_patch=repair_row["diff_patch"] or "",
                        ),
                        smell=smell,
                        final_score=repair_row["final_score"],
                        trade_offs=trade_offs,
                    )
                )

        prioritized_repairs.sort(key=lambda pr: pr.final_score)

        return AnalysisResult(
            analysis_id=analysis_id,
            dockerfile_path=analysis_row["dockerfile_path"],
            detected_smells=detected_smells,
            prioritized_repairs=prioritized_repairs,
        )

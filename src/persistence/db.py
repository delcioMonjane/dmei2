import sqlite3
from pathlib import Path
from typing import List
import yaml
from src.domain.models import AnalysisResult, Smell, PrioritizedRepair, TradeOff

def get_db_path() -> Path:
    """Reads the database path from the settings config."""
    config_dir = Path(__file__).parent.parent.parent / 'config'
    db_path_str = "docker_prioritizer.db"  # Default fallback
    for settings_path in (config_dir / 'settings.yaml', config_dir / 'settings.local.yaml'):
        if settings_path.exists():
            with open(settings_path, 'r') as f:
                settings = yaml.safe_load(f) or {}
                db_path_str = settings.get("database_path", db_path_str)
    return Path(db_path_str)

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
                negative_attribute TEXT,
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

        for prio_repair in analysis.prioritized_repairs:
            repair = prio_repair.repair
            smell = prio_repair.smell
            cursor.execute("INSERT INTO repairs (id, smell_id, description, diff_patch, final_score) VALUES (?, ?, ?, ?, ?)",
                           (repair.repair_id, smell.smell_id, repair.description, repair.diff_patch, prio_repair.final_score))

            for tradeoff in prio_repair.trade_offs:
                cursor.execute("INSERT INTO tradeoffs (repair_id, positive_attribute, negative_attribute, explanation) VALUES (?, ?, ?, ?)",
                               (repair.repair_id, tradeoff.positive_impact.attribute.value, tradeoff.negative_impact.attribute.value, tradeoff.explanation))
        conn.commit()

def get_analysis(analysis_id: str):
    # This is a simplified stub. A full implementation would need to reconstruct the object.
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT dockerfile_path FROM analyses WHERE id = ?", (analysis_id,))
        row = cursor.fetchone()
        if row:
            return {"dockerfile_path": row[0]}
        return None

import sys
from pathlib import Path
from rich import print
from rich.table import Table
import yaml
import uuid

from src.integrations.parfum.client import ParfumIntegration
from src.prioritization.engine import prioritize_repairs
from src.domain.models import DeveloperPreferences, QualityAttribute, AnalysisResult, Smell
from src.reports import exporter
from src.persistence import db
from typing import List

def show_help():
    print("Usage: python src/cli/main.py [COMMAND] [ARGS...]")
    print("\nCommands:")
    print("  prioritize [DOCKERFILE_PATH] [CONFIG_PATH]   - Prioritize repairs for a Dockerfile.")
    print("  analyze    [DOCKERFILE_PATH]                  - Analyze a Dockerfile for smells.")
    print("  compare    [BEFORE_PATH] [AFTER_PATH]         - Compare two Dockerfiles.")
    print("  apply      [DOCKERFILE_PATH] [OUTPUT_PATH]    - Auto-repair the Dockerfile.")

def prioritize_command(args):
    if len(args) < 1:
        print("[red]Error: Missing DOCKERFILE_PATH for prioritize command.[/red]")
        show_help()
        return

    file_path = Path(args[0])
    config_path = Path(args[1]) if len(args) > 1 else None

    client = ParfumIntegration()
    smells = client.analyze(file_path)

    prefs = DeveloperPreferences()
    if config_path and config_path.exists():
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f)
            if 'weights' in data:
                weights = {QualityAttribute(k): v for k, v in data['weights'].items()}
                prefs = DeveloperPreferences(weights=weights)

    prioritized_repairs = prioritize_repairs(smells, prefs)

    analysis_id = str(uuid.uuid4())
    db.init_db()

    result = AnalysisResult(
        analysis_id=analysis_id,
        dockerfile_path=str(file_path),
        detected_smells=smells,
        prioritized_repairs=prioritized_repairs
    )
    db.save_analysis(result)

    exporter.print_console_report(prioritized_repairs, str(file_path))
    print(f"\n[dim]Analysis saved with ID: {analysis_id}[/dim]")

def analyze_command(args):
    if len(args) < 1:
        print("[red]Error: Missing DOCKERFILE_PATH for analyze command.[/red]")
        show_help()
        return

    file_path = Path(args[0])
    client = ParfumIntegration()
    smells = client.analyze(file_path)
    print(f"[green]Successfully analyzed {file_path}. Found {len(smells)} smells.[/green]")
    for smell in smells:
        print(f"- {smell.name} (Line {smell.line_number})")

def calculate_total_impact(smells: List[Smell]) -> dict:
    total_impacts = {qa.value: 0 for qa in QualityAttribute}
    for smell in smells:
        for impact in smell.impacts:
            total_impacts[impact.attribute.value] += impact.score
    return total_impacts

def compare_command(args):
    if len(args) < 2:
        print("[red]Error: Missing BEFORE_PATH and AFTER_PATH for compare command.[/red]")
        show_help()
        return

    before_path = Path(args[0])
    after_path = Path(args[1])

    client = ParfumIntegration()

    print(f"[bold]Analyzing 'before' file: {before_path}[/bold]")
    before_smells = client.analyze(before_path)
    before_impacts = calculate_total_impact(before_smells)

    print(f"[bold]Analyzing 'after' file: {after_path}[/bold]")
    after_smells = client.analyze(after_path)
    after_impacts = calculate_total_impact(after_smells)

    table = Table(title="Refactoring Impact Comparison")
    table.add_column("Quality Attribute", style="cyan")
    table.add_column("Before Score", style="red")
    table.add_column("After Score", style="green")
    table.add_column("Improvement", style="bold green")

    for qa in QualityAttribute:
        before_score = before_impacts[qa.value]
        after_score = after_impacts[qa.value]
        improvement = after_score - before_score
        table.add_row(qa.value, str(before_score), str(after_score), f"{improvement:+.0f}")

    print(table)

def apply_command(args):
    if len(args) < 1:
        print("[red]Error: Missing DOCKERFILE_PATH for apply command.[/red]")
        show_help()
        return

    file_path = Path(args[0])
    output_path = Path(args[1]) if len(args) > 1 else None

    client = ParfumIntegration()
    print(f"[bold]Applying automatic repairs to {file_path}...[/bold]")
    success = client.repair(file_path, output_path)

    if success and output_path:
        print(f"[bold green]Repaired Dockerfile saved to {output_path}[/bold green]")
    elif success:
         print(f"[bold green]Repairs applied to {file_path}[/bold green]")

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        show_help()
    else:
        command = args[0]
        command_args = args[1:]
        if command == "prioritize":
            prioritize_command(command_args)
        elif command == "analyze":
            analyze_command(command_args)
        elif command == "compare":
            compare_command(command_args)
        elif command == "apply":
            apply_command(command_args)
        else:
            print(f"[red]Error: Unknown command '{command}'[/red]")
            show_help()

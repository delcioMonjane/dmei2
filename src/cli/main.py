from pathlib import Path
from typing import List, Optional

import typer
import yaml
from rich import print
from rich.console import Console
from rich.table import Table

from src.domain.models import AnalysisResult, DeveloperPreferences, QualityAttribute, Smell
from src.integrations.parfum.client import ParfumIntegration
from src.persistence import db
from src.prioritization.engine import prioritize_repairs
from src.reports import exporter
import uuid

app = typer.Typer(
    name="docker-prioritizer",
    help="Detects Dockerfile smells and ranks their repairs by trade-off-aware priority.",
    add_completion=False,
    no_args_is_help=True,
)

_REPORT_WRITERS = {
    "json": exporter.to_json,
    "csv": exporter.to_csv,
    "md": exporter.to_markdown,
}


def _load_preferences(config_path: Optional[Path]) -> DeveloperPreferences:
    if config_path is None:
        return DeveloperPreferences()
    with open(config_path, "r") as f:
        data = yaml.safe_load(f) or {}
    weights = data.get("weights", {})
    return DeveloperPreferences(weights={QualityAttribute(k): v for k, v in weights.items()})


def _calculate_total_impact(smells: List[Smell]) -> dict:
    totals = {qa.value: 0.0 for qa in QualityAttribute}
    for smell in smells:
        for impact in smell.impacts:
            totals[impact.attribute.value] += impact.score
    return totals


@app.command()
def analyze(
    dockerfile_path: Path = typer.Argument(..., exists=True, help="Path to the Dockerfile to analyze."),
):
    """Run smell detection on a Dockerfile and print the findings."""
    client = ParfumIntegration()
    smells = client.analyze(dockerfile_path)
    print(f"[green]Detected {len(smells)} smell(s) in {dockerfile_path}[/green]")
    for smell in smells:
        print(f"- {smell.name} (line {smell.line_number})")


@app.command()
def prioritize(
    dockerfile_path: Path = typer.Argument(..., exists=True, help="Path to the Dockerfile to analyze."),
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", exists=True, help="YAML file with developer quality-attribute weights."
    ),
):
    """Detect smells and rank their repairs by trade-off-aware priority score."""
    client = ParfumIntegration()
    smells = client.analyze(dockerfile_path)
    prefs = _load_preferences(config)
    prioritized_repairs = prioritize_repairs(smells, prefs)

    analysis_id = str(uuid.uuid4())
    db.init_db()
    result = AnalysisResult(
        analysis_id=analysis_id,
        dockerfile_path=str(dockerfile_path),
        detected_smells=smells,
        prioritized_repairs=prioritized_repairs,
    )
    db.save_analysis(result)

    exporter.print_console_report(prioritized_repairs, str(dockerfile_path))
    print(f"\n[dim]Analysis saved with ID: {analysis_id}[/dim]")


@app.command()
def apply(
    dockerfile_path: Path = typer.Argument(..., exists=True, help="Path to the Dockerfile to repair."),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Where to write the repaired Dockerfile (defaults to overwriting the input)."
    ),
):
    """Apply Parfum's automated repairs to a Dockerfile."""
    client = ParfumIntegration()
    target = output or dockerfile_path
    print(f"[bold]Applying automatic repairs to {dockerfile_path}...[/bold]")
    success, _ = client.repair_and_get_smells(dockerfile_path, target)

    if not success:
        raise typer.Exit(code=1)
    print(f"[bold green]Repaired Dockerfile saved to {target}[/bold green]")


@app.command()
def compare(
    before_path: Path = typer.Argument(..., exists=True, help="Dockerfile before refactoring."),
    after_path: Path = typer.Argument(..., exists=True, help="Dockerfile after refactoring."),
):
    """Compare the quality-attribute profile of two Dockerfiles."""
    client = ParfumIntegration()

    print(f"[bold]Analyzing 'before' file: {before_path}[/bold]")
    before_impacts = _calculate_total_impact(client.analyze(before_path))

    print(f"[bold]Analyzing 'after' file: {after_path}[/bold]")
    after_impacts = _calculate_total_impact(client.analyze(after_path))

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

    Console().print(table)


@app.command()
def report(
    analysis_id: str = typer.Argument(..., help="Analysis ID returned by a previous 'prioritize' run."),
    format: str = typer.Option("md", "--format", "-f", help="Output format: json, csv, or md."),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output file path (defaults to <analysis_id>.<format>)."
    ),
):
    """Re-export a previously stored analysis as JSON, CSV, or Markdown."""
    writer = _REPORT_WRITERS.get(format)
    if writer is None:
        print(f"[red]Unsupported format '{format}'. Choose from: {', '.join(_REPORT_WRITERS)}.[/red]")
        raise typer.Exit(code=1)

    db.init_db()
    analysis = db.get_analysis(analysis_id)
    if analysis is None:
        print(f"[red]No analysis found with ID: {analysis_id}[/red]")
        raise typer.Exit(code=1)

    output_path = output or Path(f"{analysis_id}.{format}")
    writer(analysis.prioritized_repairs, str(output_path))
    print(f"[green]Report written to {output_path}[/green]")


if __name__ == "__main__":
    app()

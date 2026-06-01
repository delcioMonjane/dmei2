from typing import List
from src.domain.models import PrioritizedRepair
from rich.console import Console
from rich.table import Table
import pandas as pd
import json

def print_console_report(prioritized_repairs: List[PrioritizedRepair], dockerfile_path: str):
    console = Console()
    console.print(f"[bold blue]Detected {len(prioritized_repairs)} smells in {dockerfile_path}[/bold blue]")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Priority", style="dim", width=12)
    table.add_column("Smell & Repair")
    table.add_column("Score", justify="right")
    table.add_column("Impact")
    table.add_column("Trade-offs")

    for i, item in enumerate(prioritized_repairs):
        impact_str = " | ".join([f"{imp.attribute.value}: {imp.score:+.0f}" for imp in item.smell.impacts])
        tradeoff_str = "\n".join([f"[yellow]{to.explanation}[/yellow]" for to in item.trade_offs])

        table.add_row(
            f"{i+1}",
            f"[bold]{item.smell.name}[/bold]\n[dim]{item.repair.description}[/dim]",
            f"{item.final_score:.2f}",
            impact_str,
            tradeoff_str if item.trade_offs else "None"
        )

    console.print(table)

def to_json(prioritized_repairs: List[PrioritizedRepair], output_path: str):
    data = [item.model_dump() for item in prioritized_repairs]
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)

def to_csv(prioritized_repairs: List[PrioritizedRepair], output_path: str):
    records = []
    for item in prioritized_repairs:
        record = {
            "smell_name": item.smell.name,
            "repair_description": item.repair.description,
            "score": item.final_score,
        }
        for impact in item.smell.impacts:
            record[f"impact_{impact.attribute.value.lower()}"] = impact.score
        records.append(record)

    df = pd.DataFrame(records)
    df.to_csv(output_path, index=False)

def to_markdown(prioritized_repairs: List[PrioritizedRepair], output_path: str):
    with open(output_path, 'w') as f:
        f.write("# Prioritization Report\n\n")
        for i, item in enumerate(prioritized_repairs):
            f.write(f"## {i+1}. {item.smell.name} (Score: {item.final_score:.2f})\n\n")
            f.write(f"**Repair:** {item.repair.description}\n\n")
            f.write("**Impacts:**\n")
            for impact in item.smell.impacts:
                f.write(f"- {impact.attribute.value}: {impact.score:+.0f}\n")

            if item.trade_offs:
                f.write("\n**Trade-offs:**\n")
                for to in item.trade_offs:
                    f.write(f"- {to.explanation}\n")
            f.write("\n---\n")

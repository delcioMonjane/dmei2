import subprocess
import sys
from pathlib import Path
import csv
import time
import json
import uuid
import shutil
import re
import argparse
import statistics

# --- CORRECTED PATH INSERT ---
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.integrations.parfum.client import ParfumIntegration
from src.cli.main import calculate_total_impact
from src.domain.models import QualityAttribute, AnalysisResult
from src.persistence import db

# --- Configuration ---
REPOSITORIES_DIR = Path(__file__).parent / 'repositories'
SUMMARY_RESULTS_FILE = Path(__file__).parent / 'evaluation_summary.csv'
SMELL_DETAILS_FILE = Path(__file__).parent / 'smell_details.csv'
# ---

def check_prerequisites():
    """Checks if Docker and Trivy are installed."""
    if not shutil.which("docker"):
        print("[bold red]Error: 'docker' command not found.[/bold red]"); sys.exit(1)
    if not shutil.which("trivy"):
        print("[bold red]Error: 'trivy' command not found.[/bold red]"); sys.exit(1)
    print("[green]Docker and Trivy are installed.[/green]")

def categorize_failure(error_message: str) -> str:
    """Parses a raw error string to assign a failure category."""
    if "parse error" in error_message or "failed to parse" in error_message:
        return "PARSE_ERROR"
    if "not found" in error_message or "no such file or directory" in error_message:
        return "MISSING_CONTEXT"
    if "connection timed out" in error_message or "Temporary failure resolving" in error_message:
        return "NETWORK_DEPENDENCY"
    if "unhandled docker command" in error_message.lower():
        return "PARFUM_PARSE_ERROR"
    return "UNKNOWN_BUILD_ERROR"

def get_real_metrics(dockerfile_path: Path, num_runs: int) -> dict:
    """Builds a Docker image multiple times, measures metrics, and cleans up."""
    image_tag = f"eval-image:{uuid.uuid4()}"
    metrics = { "build_status": "SUCCESS", "failure_category": None, "build_times_s": [], "image_size_mb": None, "layer_count": None, "vulnerabilities": None }

    build_times = []
    for i in range(num_runs):
        print(f"    Building image '{image_tag}' (Run {i+1}/{num_runs})...")
        try:
            # Prune build cache for a cold build
            subprocess.run(["docker", "builder", "prune", "-f"], capture_output=True)
            start_time = time.monotonic()
            subprocess.run(
                ["docker", "build", "-t", image_tag, "-f", str(dockerfile_path), str(dockerfile_path.parent)],
                check=True, capture_output=True, text=True, encoding='utf-8', errors='replace'
            )
            build_times.append(time.monotonic() - start_time)
        except subprocess.CalledProcessError as e:
            print(f"    [yellow]Build failed. Recording reason.[/yellow]")
            metrics["build_status"] = "FAILURE"
            metrics["failure_category"] = categorize_failure(e.stderr)
            return metrics

    metrics["build_time_s"] = statistics.median(build_times) if build_times else None

    try:
        print("    Inspecting image...")
        inspect_result = subprocess.run(
            ["docker", "image", "inspect", image_tag],
            check=True, capture_output=True, text=True, encoding='utf-8'
        )
        inspect_data = json.loads(inspect_result.stdout)[0]
        metrics["image_size_mb"] = inspect_data.get("Size", 0) / (1024 * 1024)
        metrics["layer_count"] = len(inspect_data.get("RootFS", {}).get("Layers", []))

        print("    Scanning for vulnerabilities with Trivy...")
        trivy_result = subprocess.run(
            ["trivy", "image", "--format", "json", "--severity", "CRITICAL,HIGH", image_tag],
            capture_output=True, text=True, encoding='utf-8'
        )
        if trivy_result.stdout:
            trivy_data = json.loads(trivy_result.stdout)
            metrics["vulnerabilities"] = len(trivy_data.get("Results") or [])
        else:
            metrics["vulnerabilities"] = 0
    finally:
        print(f"    Cleaning up image '{image_tag}'...")
        subprocess.run(["docker", "rmi", "-f", image_tag], capture_output=True)

    return metrics

def main():
    parser = argparse.ArgumentParser(description="Run evaluation on a corpus of Dockerfiles.")
    parser.add_argument("--percent", type=int, default=100, help="Percentage of the corpus to process.")
    parser.add_argument("--offset", type=int, default=0, help="Offset to start processing from.")
    parser.add_argument("--runs", type=int, default=1, help="Number of build runs for median time calculation.")
    args = parser.parse_args()

    check_prerequisites()
    db.init_db()

    all_dockerfiles = sorted(list(REPOSITORIES_DIR.glob("**/Dockerfile")))
    if not all_dockerfiles:
        print(f"No Dockerfiles found in {REPOSITORIES_DIR}."); return

    start_index = args.offset
    end_index = start_index + int(len(all_dockerfiles) * (args.percent / 100))
    dockerfiles_to_process = all_dockerfiles[start_index:end_index]

    print(f"Found {len(all_dockerfiles)} total Dockerfiles. Processing slice from {start_index} to {end_index} ({len(dockerfiles_to_process)} files).")

    summary_headers = ["repo_name", "dockerfile_path", "failure_stage", "failure_category"]
    for qa in QualityAttribute: summary_headers.extend([f"before_{qa.value.lower()}", f"after_{qa.value.lower()}", f"improvement_{qa.value.lower()}"])
    for metric in ["build_time_s", "image_size_mb", "layer_count", "vulnerabilities"]: summary_headers.extend([f"{metric}_before", f"{metric}_after", f"{metric}_improvement"])

    smell_headers = ["repo_name", "smell_id", "smell_type"]
    for qa in QualityAttribute: smell_headers.append(f"predicted_impact_{qa.value.lower()}")

    with open(SUMMARY_RESULTS_FILE, 'w', newline='', encoding='utf-8') as summary_f, \
         open(SMELL_DETAILS_FILE, 'w', newline='', encoding='utf-8') as smell_f:

        summary_writer = csv.writer(summary_f, delimiter=';')
        smell_writer = csv.writer(smell_f, delimiter=';')
        summary_writer.writerow(summary_headers)
        smell_writer.writerow(smell_headers)

        client = ParfumIntegration()

        for i, dockerfile in enumerate(dockerfiles_to_process):
            repo_name = dockerfile.parent.name
            print(f"\n--- Processing {i+1}/{len(dockerfiles_to_process)}: {repo_name} ---")

            failure_stage, failure_category = "SUCCESS", None
            before_metrics, after_metrics = {}, {}
            before_impacts, after_impacts = {}, {}

            try:
                # --- BEFORE ---
                failure_stage = "before_analysis"
                before_smells = client.analyze(dockerfile)
                before_impacts = calculate_total_impact(before_smells)

                # Write per-smell details
                for smell in before_smells:
                    smell_row = [repo_name, smell.smell_id, smell.name]
                    impact_dict = {imp.attribute.value: imp.score for imp in smell.impacts}
                    for qa in QualityAttribute: smell_row.append(impact_dict.get(qa.value, 0))
                    smell_writer.writerow(smell_row)

                failure_stage = "before_build"
                before_metrics = get_real_metrics(dockerfile, args.runs)
                if before_metrics["build_status"] == "FAILURE":
                    failure_category = before_metrics["failure_category"]
                    raise Exception("Build failed")

                # --- REPAIR ---
                failure_stage = "repair_step"
                repaired_dockerfile = dockerfile.with_suffix(".repaired")
                if not client.repair(dockerfile, repaired_dockerfile):
                    failure_category = "PARFUM_REPAIR_FAILED"
                    raise Exception("Repair step failed")

                # --- AFTER ---
                failure_stage = "after_analysis"
                after_smells = client.analyze(repaired_dockerfile)
                after_impacts = calculate_total_impact(after_smells)

                failure_stage = "after_build"
                after_metrics = get_real_metrics(repaired_dockerfile)
                if after_metrics["build_status"] == "FAILURE":
                    # If 'before' succeeded and 'after' failed, it's a regression
                    failure_category = "SYNTAX_REGRESSION" if after_metrics["failure_category"] == "PARSE_ERROR" else after_metrics["failure_category"]
                    raise Exception("Build failed after repair")

            except Exception as e:
                print(f"  [red]Pipeline failed at stage '{failure_stage}': {e}[/red]")

            # --- SAVE SUMMARY RESULTS ---
            row = [repo_name, str(dockerfile.relative_to(REPOSITORIES_DIR)), failure_stage, failure_category]
            for qa in QualityAttribute:
                b_score, a_score = before_impacts.get(qa.value, 0), after_impacts.get(qa.value, 0)
                row.extend([b_score, a_score, a_score - b_score])

            for metric in ["build_time_s", "image_size_mb", "layer_count", "vulnerabilities"]:
                b_val = before_metrics.get(metric)
                a_val = after_metrics.get(metric)
                improvement = None
                if isinstance(b_val, (int, float)) and isinstance(a_val, (int, float)):
                    improvement = a_val - b_val
                row.extend([b_val or 'N/A', a_val or 'N/A', improvement if improvement is not None else 'N/A'])

            summary_writer.writerow(row)
            print(f"[bold green]Summary results for {repo_name} saved.[/bold green]")

            if 'repaired_dockerfile' in locals() and repaired_dockerfile.exists():
                repaired_dockerfile.unlink()

    print(f"\nEvaluation complete.")

if __name__ == "__main__":
    main()

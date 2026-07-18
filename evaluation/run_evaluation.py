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

# Ensure the main src directory is in the Python path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src.integrations.parfum.client import ParfumIntegration
from src.cli.main import calculate_total_impact
from src.domain.models import QualityAttribute, AnalysisResult
from src.persistence import db

# --- Configuration ---
REPOSITORIES_DIR = Path(__file__).parent / 'repositories'
RESULTS_FILE = Path(__file__).parent / 'evaluation_results.csv'
# ---

def check_prerequisites():
    """Checks if Docker and Trivy are installed."""
    if not shutil.which("docker"):
        print("[bold red]Error: 'docker' command not found. Please install Docker Desktop and ensure it's running.[/bold red]")
        sys.exit(1)
    if not shutil.which("trivy"):
        print("[bold red]Error: 'trivy' command not found. Please install Trivy.[/bold red]")
        sys.exit(1)
    print("[green]Docker and Trivy are installed.[/green]")

def get_build_failure_reason(error_message: str) -> str:
    """Extracts a concise, one-line error from a Docker build log."""
    patterns = [
        r"The command '.+' returned a non-zero code: \d+",
        r"executor failed running .+",
        r"failed to solve: .+",
        r"ERROR: .+",
    ]
    for pattern in patterns:
        match = re.search(pattern, error_message)
        if match:
            return match.group(0).strip().replace(';',',')
    lines = [line.strip().replace(';',',') for line in error_message.strip().split('\n') if line.strip()]
    return lines[-1] if lines else "Unknown build error"

def get_real_metrics(dockerfile_path: Path) -> dict:
    """Builds a Docker image, measures its metrics, and then cleans up."""
    image_tag = f"eval-image:{uuid.uuid4()}"
    metrics = { "build_status": "SUCCESS", "build_time_s": None, "image_size_mb": None, "vulnerabilities": None }

    print(f"  Building image '{image_tag}' from context: {dockerfile_path.parent}")
    try:
        start_time = time.monotonic()
        build_context = dockerfile_path.parent
        subprocess.run(
            ["docker", "build", "-t", image_tag, "-f", str(dockerfile_path), str(build_context)],
            check=True, capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        metrics["build_time_s"] = time.monotonic() - start_time
    except subprocess.CalledProcessError as e:
        print(f"  [yellow]Build failed for {dockerfile_path.name}. Recording reason.[/yellow]")
        metrics["build_status"] = get_build_failure_reason(e.stderr)
        return metrics

    try:
        print("  Getting image size...")
        size_result = subprocess.run(
            ["docker", "image", "inspect", image_tag, "--format", "{{.Size}}"],
            check=True, capture_output=True, text=True, encoding='utf-8'
        )
        metrics["image_size_mb"] = int(size_result.stdout.strip()) / (1024 * 1024)

        print("  Scanning for vulnerabilities with Trivy...")
        trivy_result = subprocess.run(
            ["trivy", "image", "--format", "json", "--severity", "CRITICAL,HIGH", image_tag],
            capture_output=True, text=True, encoding='utf-8'
        )
        if trivy_result.stdout:
            trivy_data = json.loads(trivy_result.stdout)
            results_list = trivy_data.get("Results") or []
            metrics["vulnerabilities"] = len(results_list) if results_list else 0
        else:
            metrics["vulnerabilities"] = 0
    finally:
        print(f"  Cleaning up image '{image_tag}'...")
        subprocess.run(["docker", "rmi", "-f", image_tag], capture_output=True)

    return metrics

def main():
    """Main evaluation script."""
    parser = argparse.ArgumentParser(description="Run evaluation on a corpus of Dockerfiles.")
    parser.add_argument(
        "--percent",
        type=int,
        default=100,
        help="The percentage of the corpus to process (e.g., 10 for 10%%)."
    )
    args = parser.parse_args()

    check_prerequisites()
    db.init_db()

    all_dockerfiles = list(REPOSITORIES_DIR.glob("**/Dockerfile"))
    if not all_dockerfiles:
        print(f"No Dockerfiles found in {REPOSITORIES_DIR}. Please run the clone script first.")
        return

    # Calculate the sample size based on the percentage
    sample_size = int(len(all_dockerfiles) * (args.percent / 100))
    dockerfiles_to_process = all_dockerfiles[:sample_size]

    print(f"Found {len(all_dockerfiles)} total Dockerfiles. Processing {len(dockerfiles_to_process)} ({args.percent}%) of them.")

    headers = ["repo_name", "dockerfile_path", "build_status_before", "build_status_after"]
    for qa in QualityAttribute:
        headers.extend([f"before_{qa.value.lower()}", f"after_{qa.value.lower()}", f"improvement_{qa.value.lower()}"])
    headers.extend(["build_time_s_before", "build_time_s_after", "build_time_s_improvement"])
    headers.extend(["image_size_mb_before", "image_size_mb_after", "image_size_mb_improvement"])
    headers.extend(["vulnerabilities_before", "vulnerabilities_after", "vulnerabilities_improvement"])

    with open(RESULTS_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(headers)

        client = ParfumIntegration()

        for i, dockerfile in enumerate(dockerfiles_to_process):
            repo_name = dockerfile.parent.name
            print(f"\n--- Processing {i+1}/{len(dockerfiles_to_process)}: {repo_name} ---")
            repaired_dockerfile = dockerfile.with_suffix(".repaired")

            try:
                # --- BEFORE ---
                print("Analyzing 'before' state...")
                before_smells = client.analyze(dockerfile)
                before_impacts = calculate_total_impact(before_smells)

                analysis_id = str(uuid.uuid4())
                analysis_result = AnalysisResult(
                    analysis_id=analysis_id,
                    dockerfile_path=str(dockerfile.relative_to(REPOSITORIES_DIR)),
                    detected_smells=before_smells,
                    prioritized_repairs=[]
                )
                db.save_analysis(analysis_result)
                print(f"  Saved raw analysis to DB with ID: {analysis_id}")

                before_metrics = get_real_metrics(dockerfile)

                # --- REPAIR & AFTER ---
                after_metrics = None
                if before_metrics["build_status"] == "SUCCESS":
                    print("Applying automated repairs...")
                    if client.repair(dockerfile, repaired_dockerfile):
                        print("Analyzing 'after' state...")
                        after_smells = client.analyze(repaired_dockerfile)
                        after_impacts = calculate_total_impact(after_smells)
                        after_metrics = get_real_metrics(repaired_dockerfile)
                    else:
                        print(f"Skipping repair for {dockerfile.name} due to repair failure.")
                        after_smells, after_impacts = [], {}
                else:
                    after_smells, after_impacts = [], {}

                # --- SAVE CSV RESULTS ---
                row = [repo_name, str(dockerfile.relative_to(REPOSITORIES_DIR)), before_metrics["build_status"], after_metrics["build_status"] if after_metrics else 'N/A']

                for qa in QualityAttribute:
                    before_score = before_impacts.get(qa.value, 0)
                    after_score = after_impacts.get(qa.value, 0)
                    row.extend([before_score, after_score, after_score - before_score])

                for metric_key in ["build_time_s", "image_size_mb", "vulnerabilities"]:
                    before_val = before_metrics.get(metric_key, 'N/A')
                    after_val = after_metrics.get(metric_key, 'N/A') if after_metrics else 'N/A'
                    improvement = 'N/A'
                    if isinstance(before_val, (int, float)) and isinstance(after_val, (int, float)):
                        improvement = after_val - before_val
                    row.extend([before_val, after_val, improvement])

                writer.writerow(row)
                print(f"[bold green]Results for {repo_name} saved.[/bold green]")

            except Exception as e:
                print(f"[bold red]An unexpected error occurred processing {repo_name}: {e}[/bold red]")
            finally:
                if repaired_dockerfile.exists():
                    repaired_dockerfile.unlink()

    print(f"\nEvaluation complete. Results saved to {RESULTS_FILE}.")

if __name__ == "__main__":
    main()

import json
from pathlib import Path
import subprocess
import sys

# --- Configuration ---
METADATA_FILE = Path(__file__).parent / 'corpus' / 'github_metadata.jsonl'
REPOSITORIES_DIR = Path(__file__).parent / 'repositories'
# ---

def check_prerequisites():
    """Checks if Git is installed."""
    if not shutil.which("git"):
        print("[bold red]Error: 'git' command not found. Please install Git.[/bold red]")
        sys.exit(1)
    print("[green]Git is installed.[/green]")

def main():
    """
    Reads the metadata file and clones the repositories into the evaluation directory.
    """
    check_prerequisites()

    if not METADATA_FILE.exists():
        print(f"Error: Metadata file not found at {METADATA_FILE}")
        print("Please run the scraping script (03_github_scrape.py) first.")
        return

    REPOSITORIES_DIR.mkdir(exist_ok=True)
    print(f"Cloning repositories into: {REPOSITORIES_DIR}")

    with open(METADATA_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        total_repos = len(lines)

        for i, line in enumerate(lines):
            try:
                meta = json.loads(line)
                repo_name = meta.get("repo")
                if not repo_name:
                    continue

                # Create a safe directory name from the repo name
                repo_dir_name = repo_name.replace('/', '_')
                target_dir = REPOSITORIES_DIR / repo_dir_name

                print(f"\n--- Processing {i+1}/{total_repos}: {repo_name} ---")

                if target_dir.exists():
                    print(f"  Repository already exists at {target_dir}. Skipping clone.")
                    continue

                repo_url = f"https://github.com/{repo_name}.git"

                print(f"  Cloning {repo_url}...")

                # We use --depth 1 to do a shallow clone, which is much faster
                # and smaller as it doesn't download the full git history.
                subprocess.run(
                    ["git", "clone", "--depth", "1", repo_url, str(target_dir)],
                    check=True,
                    capture_output=True,
                    text=True
                )

                print(f"  Successfully cloned to {target_dir}")

            except json.JSONDecodeError:
                print(f"Warning: Skipping malformed line in metadata file: {line.strip()}")
            except subprocess.CalledProcessError as e:
                print(f"  [red]Error cloning {repo_name}: {e.stderr}[/red]")
            except Exception as e:
                print(f"  [red]An unexpected error occurred: {e}[/red]")

    print("\nCloning process complete.")
    print(f"Next, run 'poetry run python evaluation/run_evaluation.py' to start the analysis.")

if __name__ == "__main__":
    # Need to import shutil for the prerequisite check
    import shutil
    main()

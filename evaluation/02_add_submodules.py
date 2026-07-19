import json
from pathlib import Path
import subprocess
import sys

# --- Configuration ---
METADATA_FILE = Path(__file__).parent / 'corpus' / 'github_metadata.jsonl'
REPOSITORIES_DIR = Path(__file__).parent / 'repositories'
# ---

def main():
    """
    Reads the metadata file and adds each repository as a Git submodule.
    """
    if not METADATA_FILE.exists():
        print(f"Error: Metadata file not found at {METADATA_FILE}")
        print("Please run the scraping script (03_github_scrape.py) first.")
        return

    REPOSITORIES_DIR.mkdir(exist_ok=True)
    print(f"Adding submodules into: {REPOSITORIES_DIR}")

    with open(METADATA_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        total_repos = len(lines)

        for i, line in enumerate(lines):
            try:
                meta = json.loads(line)
                repo_name = meta.get("repo")
                if not repo_name:
                    continue

                repo_dir_name = repo_name.replace('/', '_')
                target_dir = REPOSITORIES_DIR / repo_dir_name

                print(f"\n--- Processing {i+1}/{total_repos}: {repo_name} ---")

                if target_dir.exists():
                    print(f"  Submodule directory already exists. Skipping.")
                    continue

                repo_url = f"https://github.com/{repo_name}.git"

                print(f"  Adding submodule {repo_url}...")

                # The 'git submodule add' command adds the repo as a submodule
                subprocess.run(
                    ["git", "submodule", "add", "--depth", "1", repo_url, str(target_dir)],
                    check=True,
                    capture_output=True,
                    text=True
                )

                print(f"  Successfully added submodule.")

            except json.JSONDecodeError:
                print(f"Warning: Skipping malformed line in metadata file: {line.strip()}")
            except subprocess.CalledProcessError as e:
                print(f"  [red]Error adding submodule {repo_name}: {e.stderr}[/red]")
            except Exception as e:
                print(f"  [red]An unexpected error occurred: {e}[/red]")

    print("\nSubmodule process complete.")
    print("Next, run 'git commit' and 'git push'.")
    print("On the server, clone with 'git clone --recurse-submodules ...'")

if __name__ == "__main__":
    main()

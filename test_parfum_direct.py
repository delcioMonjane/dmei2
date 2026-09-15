import subprocess
import sys

from src.integrations.parfum.client import get_parfum_executable_path

def test_parfum():
    # Run the repair command to see its options
    command = get_parfum_executable_path() + ["repair", "--help"]
    print(f"Running command: {' '.join(command)}")
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        print("--- STDOUT ---")
        print(result.stdout)
        print("--- STDERR ---")
        print(result.stderr)
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    test_parfum()

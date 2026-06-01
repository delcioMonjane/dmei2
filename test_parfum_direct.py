import subprocess
import sys

def test_parfum():
    # Run the repair command to see its options
    command = ["node", "C:/Users/delci/Documents/ISEP/MEI/2oAno/DMEI/parfum/docker-parfum/build/cli/index.js", "repair", "--help"]
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

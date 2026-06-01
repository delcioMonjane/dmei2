import subprocess
import json
from pathlib import Path
from typing import Dict, Any, List
from src.domain.models import Smell, RepairAction, QualityImpact, QualityAttribute
import yaml
import re
import uuid

def get_parfum_executable_path() -> List[str]:
    """Reads the path from the settings config and returns it as a list."""
    settings_path = Path("config/settings.yaml")
    if not settings_path.exists():
        return ["parfum"]

    with open(settings_path, 'r') as f:
        settings = yaml.safe_load(f)
        executable = settings.get("parfum_executable", "parfum")
        return executable.split()

class ParfumIntegration:
    def __init__(self, smell_impact_path: Path = Path("config/smell_impacts.yaml")):
        self.parfum_command = get_parfum_executable_path()
        with open(smell_impact_path, 'r') as f:
            self.smell_impacts = yaml.safe_load(f)['smells']

    def analyze(self, dockerfile_path: Path) -> List[Smell]:
        """Executes Parfum and captures the output."""
        abs_path = str(dockerfile_path.absolute())
        command_to_run = self.parfum_command + ["analyze", abs_path]

        print(f"[dim]Running command: {' '.join(command_to_run)}[/dim]")

        try:
            result = subprocess.run(
                command_to_run,
                capture_output=True,
                text=True,
                check=True,
                shell=False
            )

            if not result.stdout.strip():
                 print(f"[red]Error: Parfum executed successfully but returned empty output.[/red]")
                 return []

            return self._parse_text_output(result.stdout)

        except FileNotFoundError:
            print(f"[red]Error: Command '{command_to_run[0]}' not found. Please check your config/settings.yaml[/red]")
            return []
        except subprocess.CalledProcessError as e:
            print(f"[red]Parfum execution failed (Exit Code: {e.returncode}).[/red]")
            print(f"[red]Stderr: {e.stderr}[/red]")
            print(f"[red]Stdout: {e.stdout}[/red]")
            return []

    def repair(self, dockerfile_path: Path, output_path: Path = None) -> bool:
        """Executes Parfum to repair the Dockerfile."""
        abs_path = str(dockerfile_path.absolute())
        command_to_run = self.parfum_command + ["repair", abs_path]

        if output_path:
            command_to_run.extend(["-o", str(output_path.absolute())])

        print(f"[dim]Running command: {' '.join(command_to_run)}[/dim]")

        try:
            result = subprocess.run(
                command_to_run,
                capture_output=True,
                text=True,
                check=True,
                shell=False
            )
            print(f"[green]Successfully applied repairs.[/green]")
            return True
        except FileNotFoundError:
            print(f"[red]Error: Command '{command_to_run[0]}' not found.[/red]")
            return False
        except subprocess.CalledProcessError as e:
            print(f"[red]Parfum repair failed (Exit Code: {e.returncode}).[/red]")
            print(f"[red]Stderr: {e.stderr}[/red]")
            return False

    def _parse_text_output(self, text_output: str) -> List[Smell]:
        """Parses the human-readable text output from Parfum."""
        smells = []
        violation_pattern = re.compile(r"\[VIOLATION\] -> (\w+) at (\d+):\d+")

        for match in violation_pattern.finditer(text_output):
            smell_name = match.group(1)
            line_number = int(match.group(2))

            impacts = self._get_smell_impacts(smell_name)

            # Generate a guaranteed unique UUID for each entity
            smell_id = str(uuid.uuid4())
            repair_id = str(uuid.uuid4())

            placeholder_repair = RepairAction(
                repair_id=repair_id,
                description=f"Auto-repair via Parfum engine",
                diff_patch=""
            )

            smell = Smell(
                smell_id=smell_id,
                name=smell_name,
                line_number=line_number,
                impacts=impacts,
                available_repairs=[placeholder_repair]
            )
            smells.append(smell)
        return smells

    def _get_smell_impacts(self, smell_name: str) -> List[QualityImpact]:
        """Maps a smell name to its quality impacts from the config file."""
        impacts = []
        mapped_name = ""

        smell_name_lower = smell_name.lower()

        if "aptgetinstallusenorec" in smell_name_lower:
            mapped_name = "CACHE_NOT_CLEANED"
        elif "aptgetinstallthenremoveaptlists" in smell_name_lower:
            mapped_name = "CACHE_NOT_CLEANED"
        elif "pipusenocachedir" in smell_name_lower:
            mapped_name = "PIP_NO_CACHE_DIR"
        elif "dl3002" in smell_name_lower:
            mapped_name = "HADOLINT_DL3002"
        elif "latesttag" in smell_name_lower:
             mapped_name = "LATEST_TAG_USED"
        elif "runasroot" in smell_name_lower:
             mapped_name = "RUN_AS_ROOT"

        if mapped_name and mapped_name in self.smell_impacts:
            # Create a dictionary for all QAs, initialized to 0
            full_impact = {qa.value: 0 for qa in QualityAttribute}
            # Update with the scores from the config
            full_impact.update(self.smell_impacts[mapped_name])

            for qa_name, qa_score in full_impact.items():
                impacts.append(QualityImpact(attribute=QualityAttribute(qa_name), score=qa_score))
        return impacts

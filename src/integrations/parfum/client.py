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

    def _run_parfum_command(self, command: List[str]) -> subprocess.CompletedProcess:
        """A robust wrapper for running Parfum subprocesses."""
        print(f"[dim]Running command: {' '.join(command)}[/dim]")
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            shell=False,
            encoding='utf-8', # Explicitly set encoding to prevent errors on Windows
            errors='replace'   # Replace any characters that can't be decoded
        )

    def analyze(self, dockerfile_path: Path) -> List[Smell]:
        """Executes Parfum and captures the output."""
        abs_path = str(dockerfile_path.absolute())
        command_to_run = self.parfum_command + ["analyze", abs_path]

        try:
            result = self._run_parfum_command(command_to_run)
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

        try:
            self._run_parfum_command(command_to_run)
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
        smells = []
        violation_pattern = re.compile(r"\[VIOLATION\] -> (\w+) at (\d+:\d+ to \d+:\d+)\n\s*(.+?)\n\s*(.+)")

        for match in violation_pattern.finditer(text_output):
            smell_name, line_info, description, line_content = match.groups()
            line_number = int(line_info.split(':')[0])
            impacts = self._get_smell_impacts(smell_name, line_content)

            if not impacts: continue

            smell_id, repair_id = str(uuid.uuid4()), str(uuid.uuid4())
            repair_description = f"Fix for '{smell_name}' on line {line_number}: {description}"

            smells.append(Smell(
                smell_id=smell_id, name=smell_name, line_number=line_number, impacts=impacts,
                available_repairs=[RepairAction(repair_id=repair_id, description=repair_description, diff_patch="")]
            ))
        return smells

    def _get_smell_impacts(self, smell_name: str, line_content: str) -> List[QualityImpact]:
        impacts = []
        smell_name_lower = smell_name.lower()

        def add_impacts(mapped_name: str):
            if mapped_name in self.smell_impacts:
                full_impact = {qa.value: 0 for qa in QualityAttribute}
                full_impact.update(self.smell_impacts[mapped_name])
                for qa_name, qa_score in full_impact.items():
                    impacts.append(QualityImpact(attribute=QualityAttribute(qa_name), score=qa_score))

        # Mapping logic...
        if "runasroot" in smell_name_lower or "dl3002" in smell_name_lower: add_impacts("RUN_AS_ROOT")
        if "curlusehttpsurl" in smell_name_lower or "wgetusehttpsurl" in smell_name_lower: add_impacts("INSECURE_URL")
        if "dl3020" in smell_name_lower: add_impacts("ADD_INSTEAD_OF_COPY")
        if "dl3004" in smell_name_lower: add_impacts("UNPREDICTABLE_SUDO")
        if "aptgetinstallthenremoveaptlists" in smell_name_lower or "yuminstallrmvarcacheyum" in smell_name_lower or "npmcachecleanafterinstall" in smell_name_lower or "yarncachecleanafterinstall" in smell_name_lower: add_impacts("CACHE_NOT_CLEANED")
        if "aptgetinstallusenorec" in smell_name_lower: add_impacts("NO_INSTALL_RECOMMENDS_MISSING")
        if "pipusenocachedir" in smell_name_lower: add_impacts("PIP_NO_CACHE_DIR_MISSING")
        if "apkaddusecache" in smell_name_lower: add_impacts("APK_NO_CACHE_MISSING")
        if "rmrecursiveaftermktempd" in smell_name_lower: add_impacts("TEMP_DIR_NOT_REMOVED")
        if "tarsomethingrmthesomething" in smell_name_lower: add_impacts("ARCHIVE_NOT_REMOVED")
        if "gemupdatenodocument" in smell_name_lower: add_impacts("GEM_DOCS_NOT_SKIPPED")
        if "latesttag" in smell_name_lower: add_impacts("IMPRECISE_TAG")
        if "aptgetupdateprecedesinstall" in smell_name_lower: add_impacts("APT_UPDATE_SEPARATE")
        if "morethanoneinstall" in smell_name_lower: add_impacts("MULTIPLE_INSTALLS")
        if "gpgusehapools" in smell_name_lower: add_impacts("GPG_KEYSERVER_BEST_PRACTICE")
        if "dl3027" in smell_name_lower: add_impacts("DISCOURAGED_COMMAND")
        if "gpgusebatchflag" in smell_name_lower: add_impacts("GPG_NO_BATCH")
        if "yuminstallforceyes" in smell_name_lower: add_impacts("YUM_NO_YES_FLAG")
        if "aptgetinstallusey" in smell_name_lower: add_impacts("APTGET_NO_YES_FLAG")
        if "dl3029" in smell_name_lower: add_impacts("PLATFORM_PINNING")
        if "dl3046" in smell_name_lower: add_impacts("USELESS_LOG_ENTRIES")

        return impacts

import subprocess
import re
import uuid
from pathlib import Path
from typing import List, Tuple

import yaml

from src.domain.models import QualityAttribute, QualityImpact, RepairAction, Smell

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


def get_parfum_executable_path() -> List[str]:
    """Reads the path from the settings config and returns it as a list.

    config/settings.yaml holds the portable default; config/settings.local.yaml
    (gitignored) can override it with a machine-specific path, since
    docker-parfum is typically a locally built Node project rather than a
    globally installed binary.
    """
    executable = "docker-parfum"  # Default to a global install on PATH
    for settings_path in (CONFIG_DIR / "settings.yaml", CONFIG_DIR / "settings.local.yaml"):
        if settings_path.exists():
            with open(settings_path, "r") as f:
                settings = yaml.safe_load(f) or {}
                executable = settings.get("parfum_executable", executable)
    return executable.split()


class ParfumIntegration:
    def __init__(self, smell_impact_path: Path = None):
        self.parfum_command = get_parfum_executable_path()
        if smell_impact_path is None:
            smell_impact_path = CONFIG_DIR / "smell_impacts.yaml"
        with open(smell_impact_path, "r") as f:
            self.smell_impacts = yaml.safe_load(f)["smells"]

    def _run_command(self, command: List[str]) -> subprocess.CompletedProcess:
        """A robust wrapper for running Parfum subprocesses."""
        print(f"[dim]Running command: {' '.join(command)}[/dim]")
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            shell=False,
            encoding="utf-8",
            errors="replace",
        )

    def analyze(self, dockerfile_path: Path) -> List[Smell]:
        """
        Executes Parfum to analyze a file. This is now primarily used for the 'after' state
        to confirm if smells were fixed.
        """
        command_to_run = self.parfum_command + ["analyze", str(dockerfile_path.absolute())]
        try:
            result = self._run_command(command_to_run)
            if not result.stdout.strip():
                return []
            # The 'analyze' command might have a different output, but we can still try to parse it.
            # For now, we assume it might be the same text format.
            return self._parse_smells_from_output(result.stdout)
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            print(f"[red]Parfum analysis failed: {e}[/red]")
            return []

    def repair_and_get_smells(self, dockerfile_path: Path, output_path: Path) -> Tuple[bool, List[Smell]]:
        """
        Executes Parfum to repair the Dockerfile AND parses the output to get the
        list of smells that it attempted to fix. This is the primary data source.
        """
        command_to_run = self.parfum_command + ["repair", str(dockerfile_path.absolute()), "-o", str(output_path.absolute())]
        try:
            result = self._run_command(command_to_run)
            print(f"[green]Successfully applied repairs.[/green]")

            # Parse the detailed smell info from the repair command's output
            detected_smells = self._parse_smells_from_output(result.stdout)

            return True, detected_smells
        except FileNotFoundError:
            print(f"[red]Error: Command '{command_to_run[0]}' not found.[/red]")
            return False, []
        except subprocess.CalledProcessError as e:
            print(f"[red]Parfum repair failed (Exit Code: {e.returncode}).[/red]")
            print(f"[red]Stderr: {e.stderr}[/red]")
            return False, []

    def _parse_smells_from_output(self, text_output: str) -> List[Smell]:
        """Parses the human-readable text output from Parfum (from analyze or repair)."""
        smells = []
        # Regex to find [VIOLATION] blocks, which contain the smell info
        violation_pattern = re.compile(r"\[VIOLATION\] -> (\w+) at (\d+:\d+ to \d+:\d+)\n\s*(.+?)\n\s*(.+)")

        for match in violation_pattern.finditer(text_output):
            smell_name, line_info, description, line_content = match.groups()
            line_number = int(line_info.split(":")[0])
            impacts = self._get_smell_impacts(smell_name, line_content)

            # We only record smells that we have a defined impact for.
            if not impacts:
                continue

            smell_id, repair_id = str(uuid.uuid4()), str(uuid.uuid4())
            repair_description = f"Fix for '{smell_name}' on line {line_number}: {description}"

            smells.append(
                Smell(
                    smell_id=smell_id,
                    name=smell_name,
                    line_number=line_number,
                    impacts=impacts,
                    available_repairs=[
                        RepairAction(
                            repair_id=repair_id,
                            description=repair_description,
                            diff_patch="",
                        )
                    ],
                )
            )
        return smells

    def _get_smell_impacts(self, smell_name: str, line_content: str) -> List[QualityImpact]:
        """Checks a smell name against all known smell mappings."""
        impacts = []
        smell_name_lower = smell_name.lower()

        def add_impacts(mapped_name: str):
            if mapped_name in self.smell_impacts:
                full_impact = {qa.value: 0 for qa in QualityAttribute}
                full_impact.update(self.smell_impacts[mapped_name])
                for qa_name, qa_score in full_impact.items():
                    impacts.append(
                        QualityImpact(attribute=QualityAttribute(qa_name), score=qa_score)
                    )

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

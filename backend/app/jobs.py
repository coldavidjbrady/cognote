from __future__ import annotations

import json
import subprocess
import sys
import threading
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .importer import embed_pending_notes, import_notes_file
from .schemas import SyncRunRequest


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SyncArtifacts:
    output_dir: str
    csv_path: str
    csv_exists: bool
    jsonl_path: str
    jsonl_exists: bool
    markdown_path: str
    markdown_exists: bool
    summary_path: str
    summary_exists: bool
    state_path: str
    state_exists: bool
    xlsx_path: str
    xlsx_exists: bool


class SyncJobManager:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._lock = threading.Lock()
        self._status: dict[str, object] = self._idle_status()

    def _idle_status(self) -> dict[str, object]:
        return {
            "status": "idle",
            "job_id": None,
            "job_type": None,
            "phase": "idle",
            "message": "No setup or sync job has started yet.",
            "started_at": None,
            "finished_at": None,
            "error": None,
            "warnings": [],
            "output_dir": None,
            "artifacts": None,
            "export_summary": None,
            "import_summary": None,
            "runtime_mode": self._settings.runtime_mode,
            "app_support_dir": str(self._settings.app_support_dir),
            "exporter_path": str(self._settings.exporter_script_path),
            "exporter_command": None,
        }

    def get_status(self) -> dict[str, object]:
        with self._lock:
            return deepcopy(self._status)

    def start_setup(self, request: SyncRunRequest, *, run_async: bool = True) -> dict[str, object]:
        return self._start_job("setup", request, run_async=run_async)

    def start_sync(self, request: SyncRunRequest, *, run_async: bool = True) -> dict[str, object]:
        return self._start_job("sync", request, run_async=run_async)

    def _start_job(
        self,
        job_type: str,
        request: SyncRunRequest,
        *,
        run_async: bool,
    ) -> dict[str, object]:
        with self._lock:
            if self._status["status"] == "running":
                raise RuntimeError("A setup or sync job is already running.")

            job_id = str(uuid.uuid4())
            self._status = {
                "status": "running",
                "job_id": job_id,
                "job_type": job_type,
                "phase": "queued",
                "message": f"{job_type.capitalize()} job queued.",
                "started_at": utc_now(),
                "finished_at": None,
                "error": None,
                "warnings": [],
                "output_dir": None,
                "artifacts": None,
                "export_summary": None,
                "import_summary": None,
                "runtime_mode": self._settings.runtime_mode,
                "app_support_dir": str(self._settings.app_support_dir),
                "exporter_path": str(self._settings.exporter_script_path),
                "exporter_command": None,
            }

        if run_async:
            thread = threading.Thread(
                target=self._run_job,
                args=(job_id, job_type, request),
                name=f"cognote-{job_type}-job",
                daemon=True,
            )
            thread.start()
        else:
            self._run_job(job_id, job_type, request)

        return self.get_status()

    def _set_status(self, job_id: str, **updates: object) -> None:
        with self._lock:
            if self._status.get("job_id") != job_id:
                return
            self._status.update(updates)

    def _new_output_dir(self, job_type: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = self._settings.exports_root_dir / f"{timestamp}-{job_type}"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _artifacts_for_output_dir(self, output_dir: Path) -> SyncArtifacts:
        csv_path = output_dir / "notes_export.csv"
        jsonl_path = output_dir / "notes_export.jsonl"
        markdown_path = output_dir / "notes_merged.md"
        summary_path = output_dir / "export_summary.json"
        state_path = output_dir / ".export_state.json"
        xlsx_path = output_dir / "notes_export.xlsx"
        return SyncArtifacts(
            output_dir=str(output_dir),
            csv_path=str(csv_path),
            csv_exists=csv_path.exists(),
            jsonl_path=str(jsonl_path),
            jsonl_exists=jsonl_path.exists(),
            markdown_path=str(markdown_path),
            markdown_exists=markdown_path.exists(),
            summary_path=str(summary_path),
            summary_exists=summary_path.exists(),
            state_path=str(state_path),
            state_exists=state_path.exists(),
            xlsx_path=str(xlsx_path),
            xlsx_exists=xlsx_path.exists(),
        )

    def _validate_export_artifacts(
        self,
        artifacts: SyncArtifacts,
        request: SyncRunRequest,
    ) -> list[str]:
        warnings: list[str] = []
        if not artifacts.jsonl_exists:
            raise RuntimeError(f"Exporter completed without producing {artifacts.jsonl_path}")
        if not artifacts.csv_exists:
            raise RuntimeError(f"Exporter completed without producing {artifacts.csv_path}")
        if not artifacts.markdown_exists:
            raise RuntimeError(f"Exporter completed without producing {artifacts.markdown_path}")
        if not artifacts.summary_exists:
            warnings.append(
                "Exporter completed without export_summary.json; continuing with artifact-only status."
            )
        if request.resume_export and not artifacts.state_exists:
            warnings.append(
                "Resume export was requested, but no .export_state.json snapshot was written."
            )
        if not request.skip_xlsx and not artifacts.xlsx_exists:
            warnings.append(
                "XLSX export was not produced. This can happen when openpyxl is unavailable in the runtime."
            )
        return warnings

    def _run_export(
        self,
        output_dir: Path,
        request: SyncRunRequest,
    ) -> tuple[dict[str, object], SyncArtifacts, str, list[str], list[str]]:
        exporter_path = self._settings.exporter_script_path
        if not exporter_path.exists():
            raise RuntimeError(f"Exporter script not found at {exporter_path}")

        command = [
            sys.executable,
            str(exporter_path),
            "--output-dir",
            str(output_dir),
            "--progress-every",
            str(request.progress_every),
        ]
        if request.account:
            command.extend(["--account", request.account])
        if request.skip_xlsx:
            command.append("--skip-xlsx")
        if request.resume_export:
            command.append("--resume")

        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            cwd=str(self._settings.resource_root),
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            detail = stderr or stdout or "Unknown exporter error"
            raise RuntimeError(f"Exporter failed from {exporter_path}: {detail}")

        artifacts = self._artifacts_for_output_dir(output_dir)
        warnings = self._validate_export_artifacts(artifacts, request)

        export_summary: dict[str, object] = {}
        if artifacts.summary_exists:
            summary_path = Path(artifacts.summary_path)
            export_summary = json.loads(summary_path.read_text(encoding="utf-8"))

        stdout_lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
        stdout_excerpt = "\n".join(stdout_lines[-12:])
        return export_summary, artifacts, stdout_excerpt, warnings, command

    def _run_job(self, job_id: str, job_type: str, request: SyncRunRequest) -> None:
        try:
            output_dir = self._new_output_dir(job_type)
            self._set_status(job_id, output_dir=str(output_dir))
            self._set_status(
                job_id,
                phase="requesting_permissions",
                message="Preparing Apple Notes export. macOS may request Notes automation access.",
            )
            self._set_status(
                job_id,
                phase="exporting_notes",
                message="Exporting Apple Notes into a transitional snapshot.",
            )
            export_summary, artifacts, stdout_excerpt, warnings, command = self._run_export(
                output_dir,
                request,
            )
            self._set_status(
                job_id,
                artifacts=asdict(artifacts),
                export_summary={
                    **export_summary,
                    "stdout_excerpt": stdout_excerpt,
                },
                warnings=warnings,
                exporter_command=command,
                phase="importing_database",
                message="Importing exported notes into SQLite.",
            )
            imported, changed, archived = import_notes_file(Path(artifacts.jsonl_path), self._settings.db_path)

            embedded = 0
            if not request.skip_embeddings:
                self._set_status(
                    job_id,
                    phase="embedding_notes",
                    message="Generating embeddings for new or changed notes.",
                )
                embedded = embed_pending_notes(self._settings.db_path, self._settings)

            self._set_status(
                job_id,
                phase="archiving_missing_notes",
                message="Finalizing archive state for notes missing from the latest sync.",
            )
            self._set_status(
                job_id,
                status="complete",
                phase="complete",
                message=f"{job_type.capitalize()} complete.",
                finished_at=utc_now(),
                import_summary={
                    "imported": imported,
                    "changed": changed,
                    "archived": archived,
                    "embedded": embedded,
                    "openai_enabled": bool(self._settings.openai_api_key),
                },
            )
        except Exception as exc:
            self._set_status(
                job_id,
                status="failed",
                phase="failed",
                message=f"{job_type.capitalize()} failed.",
                finished_at=utc_now(),
                error=str(exc),
            )

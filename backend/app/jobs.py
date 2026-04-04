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
    jsonl_path: str
    markdown_path: str
    summary_path: str
    state_path: str
    xlsx_path: str


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
            "output_dir": None,
            "artifacts": None,
            "export_summary": None,
            "import_summary": None,
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
                "output_dir": None,
                "artifacts": None,
                "export_summary": None,
                "import_summary": None,
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
        return SyncArtifacts(
            output_dir=str(output_dir),
            csv_path=str(output_dir / "notes_export.csv"),
            jsonl_path=str(output_dir / "notes_export.jsonl"),
            markdown_path=str(output_dir / "notes_merged.md"),
            summary_path=str(output_dir / "export_summary.json"),
            state_path=str(output_dir / ".export_state.json"),
            xlsx_path=str(output_dir / "notes_export.xlsx"),
        )

    def _run_export(self, output_dir: Path, request: SyncRunRequest) -> tuple[dict[str, object], SyncArtifacts, str]:
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
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            detail = stderr or stdout or "Unknown exporter error"
            raise RuntimeError(f"Exporter failed: {detail}")

        artifacts = self._artifacts_for_output_dir(output_dir)
        jsonl_path = Path(artifacts.jsonl_path)
        if not jsonl_path.exists():
            raise RuntimeError(f"Exporter completed without producing {jsonl_path}")

        summary_path = Path(artifacts.summary_path)
        export_summary: dict[str, object] = {}
        if summary_path.exists():
            export_summary = json.loads(summary_path.read_text(encoding="utf-8"))

        stdout_lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
        stdout_excerpt = "\n".join(stdout_lines[-12:])
        return export_summary, artifacts, stdout_excerpt

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
            export_summary, artifacts, stdout_excerpt = self._run_export(output_dir, request)
            self._set_status(
                job_id,
                artifacts=asdict(artifacts),
                export_summary={
                    **export_summary,
                    "stdout_excerpt": stdout_excerpt,
                },
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

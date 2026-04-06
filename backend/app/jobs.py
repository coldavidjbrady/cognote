from __future__ import annotations

import importlib.util
import io
import json
import re
import subprocess
import sys
import threading
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .importer import embed_pending_notes, import_notes_file
from .schemas import SyncRunRequest

EXPORT_FOLDER_RE = re.compile(r"^\[(folder|skip)\s+(\d+)/(\d+)\]\s+(.*)$")
EXPORT_PROCESSED_RE = re.compile(r"^processed\s+(\d+)\s+notes\.\.\.$")
EXPORT_FINISHED_FOLDER_RE = re.compile(r"^finished folder with\s+(\d+)\s+notes$")
EXPORT_FALLBACK_RE = re.compile(r"^Streaming export found folders but no notes\. Retrying with bulk fallback\.\.\.$")
EXPORT_FALLBACK_RECOVERED_RE = re.compile(r"^Fallback exporter recovered\s+(\d+)\s+notes$")


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


class ExporterRunError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        command: list[str],
        stdout_text: str,
        stderr_text: str,
    ):
        super().__init__(message)
        self.command = command
        self.stdout_text = stdout_text
        self.stderr_text = stderr_text


class _LineCaptureBuffer(io.StringIO):
    def __init__(self, on_line=None):
        super().__init__()
        self._on_line = on_line
        self._partial = ""

    def write(self, text: str) -> int:
        written = super().write(text)
        if not self._on_line or not text:
            return written
        self._partial += text
        while "\n" in self._partial:
            line, self._partial = self._partial.split("\n", 1)
            self._on_line(line)
        return written

    def flush(self) -> None:
        if self._on_line and self._partial:
            self._on_line(self._partial)
            self._partial = ""
        super().flush()


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
            "export_progress": None,
            "import_progress": None,
            "import_error_log_path": None,
            "logs_dir": str(self._settings.logs_dir),
            "log_path": None,
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
                "export_progress": {
                    "notes_exported": 0,
                    "folders_completed": 0,
                    "folders_total": None,
                    "current_folder": None,
                },
                "import_progress": {
                    "notes_imported": 0,
                },
                "import_error_log_path": None,
                "logs_dir": str(self._settings.logs_dir),
                "log_path": None,
                "runtime_mode": self._settings.runtime_mode,
                "app_support_dir": str(self._settings.app_support_dir),
                "exporter_path": str(self._settings.exporter_script_path),
                "exporter_command": None,
            }

        if run_async:
            thread = threading.Thread(
                target=self._run_job,
                args=(job_id, job_type, request, True),
                name=f"cognote-{job_type}-job",
                daemon=True,
            )
            thread.start()
        else:
            self._run_job(job_id, job_type, request, False)

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

    def _new_log_path(self, job_type: str, job_id: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._settings.logs_dir.mkdir(parents=True, exist_ok=True)
        return self._settings.logs_dir / f"{timestamp}-{job_type}-{job_id[:8]}.log"

    def _format_export_message(self, progress: dict[str, object]) -> str:
        notes_exported = int(progress.get("notes_exported") or 0)
        folders_completed = int(progress.get("folders_completed") or 0)
        folders_total = progress.get("folders_total")
        current_folder = str(progress.get("current_folder") or "").strip()

        details: list[str] = []
        if notes_exported > 0:
            details.append(f"{notes_exported} notes exported so far")
        if folders_total:
            if current_folder:
                current_index = min(folders_completed + 1, int(folders_total))
                details.append(f"scanning folder {current_index} of {int(folders_total)}: {current_folder}")
            else:
                details.append(f"{folders_completed} of {int(folders_total)} folders complete")
        if not details:
            return "Exporting Apple Notes into a transitional snapshot."
        return f"Exporting Apple Notes into a transitional snapshot. {'; '.join(details)}."

    def _update_export_progress_from_line(self, job_id: str, raw_line: str) -> None:
        line = raw_line.strip()
        if not line:
            return

        status = self.get_status()
        progress = dict(status.get("export_progress") or {})
        changed = False
        message_override = None

        folder_match = EXPORT_FOLDER_RE.match(line)
        if folder_match:
            kind, current_str, total_str, folder_label = folder_match.groups()
            current = int(current_str)
            total = int(total_str)
            progress["folders_total"] = total
            progress["current_folder"] = folder_label
            progress["folders_completed"] = current if kind == "skip" else max(0, current - 1)
            changed = True

        processed_match = EXPORT_PROCESSED_RE.match(line)
        if processed_match:
            progress["notes_exported"] = int(processed_match.group(1))
            changed = True

        finished_match = EXPORT_FINISHED_FOLDER_RE.match(line)
        if finished_match:
            progress["folders_completed"] = int(progress.get("folders_completed") or 0) + 1
            progress["current_folder"] = None
            changed = True

        if EXPORT_FALLBACK_RE.match(line):
            message_override = "Exporting Apple Notes into a transitional snapshot. Retrying with bulk fallback export."
            changed = True

        fallback_recovered_match = EXPORT_FALLBACK_RECOVERED_RE.match(line)
        if fallback_recovered_match:
            progress["notes_exported"] = int(fallback_recovered_match.group(1))
            progress["current_folder"] = None
            message_override = (
                f"Exporting Apple Notes into a transitional snapshot. "
                f"Fallback export recovered {progress['notes_exported']} notes."
            )
            changed = True

        if line == "Saving XLSX workbook...":
            message_override = "Exporting Apple Notes into a transitional snapshot. Saving the optional Excel export."
            changed = True

        if changed:
            self._set_status(
                job_id,
                export_progress=progress,
                message=message_override or self._format_export_message(progress),
            )

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
        job_id: str,
        output_dir: Path,
        request: SyncRunRequest,
        *,
        live_progress: bool,
    ) -> tuple[dict[str, object], SyncArtifacts, str, list[str], list[str], str, str]:
        exporter_path = self._settings.exporter_script_path
        if not exporter_path.exists():
            raise RuntimeError(f"Exporter script not found at {exporter_path}")

        exporter_args = [
            "--output-dir",
            str(output_dir),
            "--progress-every",
            str(request.progress_every),
        ]
        if request.account:
            exporter_args.extend(["--account", request.account])
        if request.skip_xlsx:
            exporter_args.append("--skip-xlsx")
        if request.resume_export:
            exporter_args.append("--resume")

        if self._settings.is_packaged and getattr(sys, "frozen", False):
            stdout_text, stderr_text, exit_code, command = self._run_export_in_process(
                job_id,
                exporter_path,
                exporter_args,
                live_progress=live_progress,
            )
        else:
            if live_progress:
                stdout_text, stderr_text, exit_code, command = self._run_export_subprocess(
                    job_id,
                    exporter_path,
                    exporter_args,
                )
            else:
                command = [sys.executable, str(exporter_path), *exporter_args]
                proc = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    cwd=str(self._settings.resource_root),
                )
                stdout_text = proc.stdout or ""
                stderr_text = proc.stderr or ""
                exit_code = proc.returncode

        if exit_code != 0:
            stderr = stderr_text.strip()
            stdout = stdout_text.strip()
            detail = stderr or stdout or "Unknown exporter error"
            raise ExporterRunError(
                f"Exporter failed from {exporter_path}: {detail}",
                command=command,
                stdout_text=stdout_text,
                stderr_text=stderr_text,
            )

        artifacts = self._artifacts_for_output_dir(output_dir)
        warnings = self._validate_export_artifacts(artifacts, request)

        export_summary: dict[str, object] = {}
        if artifacts.summary_exists:
            summary_path = Path(artifacts.summary_path)
            export_summary = json.loads(summary_path.read_text(encoding="utf-8"))

        stdout_lines = [line for line in stdout_text.splitlines() if line.strip()]
        stdout_excerpt = "\n".join(stdout_lines[-12:])
        return export_summary, artifacts, stdout_excerpt, warnings, command, stdout_text, stderr_text

    def _run_export_in_process(
        self,
        job_id: str,
        exporter_path: Path,
        exporter_args: list[str],
        *,
        live_progress: bool,
    ) -> tuple[str, str, int, list[str]]:
        module_name = "cognote_packaged_exporter"
        spec = importlib.util.spec_from_file_location(module_name, exporter_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load packaged exporter module from {exporter_path}")

        module = importlib.util.module_from_spec(spec)
        previous_module = sys.modules.get(module_name)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            exporter_main = getattr(module, "main", None)
            if not callable(exporter_main):
                raise RuntimeError(f"Packaged exporter at {exporter_path} does not expose a callable main()")

            stdout_buffer = _LineCaptureBuffer(
                on_line=(lambda line: self._update_export_progress_from_line(job_id, line))
                if live_progress
                else None
            )
            stderr_buffer = io.StringIO()
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                exit_code = int(exporter_main(list(exporter_args)))
        finally:
            if previous_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous_module

        command = [str(exporter_path), *exporter_args]
        return stdout_buffer.getvalue(), stderr_buffer.getvalue(), exit_code, command

    def _run_export_subprocess(
        self,
        job_id: str,
        exporter_path: Path,
        exporter_args: list[str],
    ) -> tuple[str, str, int, list[str]]:
        command = [sys.executable, str(exporter_path), *exporter_args]
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(self._settings.resource_root),
            bufsize=1,
        )

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        def consume_stdout() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                stdout_lines.append(line)
                self._update_export_progress_from_line(job_id, line)
            proc.stdout.close()

        def consume_stderr() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                stderr_lines.append(line)
            proc.stderr.close()

        stdout_thread = threading.Thread(target=consume_stdout, name="cognote-export-stdout", daemon=True)
        stderr_thread = threading.Thread(target=consume_stderr, name="cognote-export-stderr", daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        exit_code = proc.wait()
        stdout_thread.join()
        stderr_thread.join()
        return "".join(stdout_lines), "".join(stderr_lines), exit_code, command

    def _write_failure_log(
        self,
        *,
        job_id: str,
        job_type: str,
        request: SyncRunRequest,
        log_path: Path,
        exc: Exception,
        trace_text: str,
        phase: str | None,
        output_dir: Path | None,
        exporter_command: list[str] | None,
        exporter_stdout: str | None,
        exporter_stderr: str | None,
    ) -> None:
        status_snapshot = self.get_status()
        request_payload = request.model_dump()
        lines = [
            f"Cognote {job_type} failure report",
            f"job_id: {job_id}",
            f"timestamp_utc: {utc_now()}",
            f"runtime_mode: {self._settings.runtime_mode}",
            f"phase: {phase or 'unknown'}",
            f"app_support_dir: {self._settings.app_support_dir}",
            f"logs_dir: {self._settings.logs_dir}",
            f"db_path: {self._settings.db_path}",
            f"exporter_path: {self._settings.exporter_script_path}",
            f"output_dir: {output_dir or ''}",
            f"exception_type: {type(exc).__name__}",
            f"error: {exc}",
            "",
            "request:",
            json.dumps(request_payload, indent=2, sort_keys=True),
            "",
            "status_snapshot:",
            json.dumps(status_snapshot, indent=2, sort_keys=True),
        ]

        if exporter_command:
            lines.extend(
                [
                    "",
                    "exporter_command:",
                    json.dumps(exporter_command, indent=2),
                ]
            )

        if exporter_stdout:
            lines.extend(
                [
                    "",
                    "exporter_stdout:",
                    exporter_stdout.rstrip(),
                ]
            )

        if exporter_stderr:
            lines.extend(
                [
                    "",
                    "exporter_stderr:",
                    exporter_stderr.rstrip(),
                ]
            )

        lines.extend(
            [
                "",
                "traceback:",
                trace_text.rstrip(),
                "",
            ]
        )
        log_path.write_text("\n".join(lines), encoding="utf-8")

    def _run_job(self, job_id: str, job_type: str, request: SyncRunRequest, live_progress: bool = False) -> None:
        output_dir: Path | None = None
        log_path: Path | None = None
        import_error_log_path: Path | None = None
        exporter_command: list[str] | None = None
        exporter_stdout: str | None = None
        exporter_stderr: str | None = None
        try:
            output_dir = self._new_output_dir(job_type)
            log_path = self._new_log_path(job_type, job_id)
            import_error_log_path = output_dir / "import-note-failures.log"
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
            export_summary, artifacts, stdout_excerpt, warnings, command, stdout_text, stderr_text = self._run_export(
                job_id,
                output_dir,
                request,
                live_progress=live_progress,
            )
            exporter_command = command
            exporter_stdout = stdout_text
            exporter_stderr = stderr_text
            final_export_progress = dict(self.get_status().get("export_progress") or {})
            if export_summary.get("total_notes") is not None:
                final_export_progress["notes_exported"] = int(export_summary["total_notes"])
            self._set_status(
                job_id,
                artifacts=asdict(artifacts),
                export_summary={
                    **export_summary,
                    "stdout_excerpt": stdout_excerpt,
                },
                export_progress=final_export_progress,
                warnings=warnings,
                exporter_command=command,
                phase="importing_database",
                message="Importing exported notes into SQLite.",
            )
            import_failures = 0

            def handle_import_progress(imported_count: int) -> None:
                self._set_status(
                    job_id,
                    import_progress={"notes_imported": imported_count},
                    message=f"Importing exported notes into SQLite. {imported_count} notes imported so far.",
                )

            def handle_note_error(issue: dict[str, object]) -> None:
                nonlocal import_failures
                import_failures += 1
                assert import_error_log_path is not None
                with import_error_log_path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "timestamp_utc": utc_now(),
                                **issue,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

            imported, changed, archived = import_notes_file(
                Path(artifacts.jsonl_path),
                self._settings.db_path,
                progress_callback=handle_import_progress if live_progress else None,
                progress_every=100,
                note_error_callback=handle_note_error,
            )

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
                message=(
                    f"{job_type.capitalize()} complete with {import_failures} skipped notes."
                    if import_failures
                    else f"{job_type.capitalize()} complete."
                ),
                finished_at=utc_now(),
                import_summary={
                    "imported": imported,
                    "changed": changed,
                    "archived": archived,
                    "embedded": embedded,
                    "failed": import_failures,
                    "openai_enabled": bool(self._settings.openai_api_key),
                },
                import_error_log_path=str(import_error_log_path) if import_failures else None,
                warnings=(
                    [
                        *warnings,
                        f"{import_failures} note(s) were skipped during import. See {import_error_log_path}."
                    ]
                    if import_failures
                    else warnings
                ),
            )
        except Exception as exc:
            if isinstance(exc, ExporterRunError):
                exporter_command = exc.command
                exporter_stdout = exc.stdout_text
                exporter_stderr = exc.stderr_text
            trace_text = traceback.format_exc()
            failure_log_path = None
            if log_path is not None:
                try:
                    self._write_failure_log(
                        job_id=job_id,
                        job_type=job_type,
                        request=request,
                        log_path=log_path,
                        exc=exc,
                        trace_text=trace_text,
                        phase=str(self.get_status().get("phase") or ""),
                        output_dir=output_dir,
                        exporter_command=exporter_command,
                        exporter_stdout=exporter_stdout,
                        exporter_stderr=exporter_stderr,
                    )
                    failure_log_path = str(log_path)
                except Exception:
                    failure_log_path = None
            self._set_status(
                job_id,
                status="failed",
                phase="failed",
                message=f"{job_type.capitalize()} failed.",
                finished_at=utc_now(),
                error=str(exc),
                log_path=failure_log_path,
                exporter_command=exporter_command,
            )

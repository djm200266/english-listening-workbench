"""
ComfyUI Process Manager - start, monitor, and stop ComfyUI as a subprocess.
Uses python_embeded to launch ComfyUI directly, no browser auto-launch.
"""

from __future__ import annotations

import os, subprocess, threading, time, json
from pathlib import Path
from typing import Any

import requests

from config import get_config

LOGS_DIR = Path(__file__).parent.parent.parent / "logs" / "runtime"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


class ComfyUIProcessManager:
    """Singleton that manages one ComfyUI subprocess."""

    _instance: ComfyUIProcessManager | None = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._proc = None
            cls._instance._owned = False
            cls._instance._starting = False
            cls._instance._last_error = None
            cls._instance._start_attempts = 0
        return cls._instance

    @classmethod
    def get_instance(cls) -> ComfyUIProcessManager:
        if cls._instance is None:
            cls._instance = cls.__new__(cls)
            cls._instance._proc = None
            cls._instance._owned = False
            cls._instance._starting = False
            cls._instance._last_error = None
            cls._instance._start_attempts = 0
        return cls._instance

    # ---- Public API ----

    def is_running(self) -> bool:
        """Check if ComfyUI is responding on port 8188 via HTTP endpoints.

        Tries /system_stats first, then /queue, then /history.
        Does NOT fall back to raw socket check (which would falsely report
        zombie/phantom processes as running).
        """
        for endpoint in ["/system_stats", "/queue", "/history"]:
            try:
                r = requests.get(f"http://127.0.0.1:8188{endpoint}",
                               timeout=3, proxies={"http": None, "https": None})
                if r.status_code == 200:
                    return True
            except Exception:
                continue
        return False

    def get_status(self) -> dict[str, Any]:
        """Return structured status for health endpoint.

        States:
        - stopped: ComfyUI is not running and not starting
        - starting: ComfyUI is being started (process launched, waiting for HTTP)
        - ready: /system_stats returns 200, checkpoint + workflow available
        - degraded: /system_stats returns 200 but checkpoint or workflow missing
        - failed: process exited with error or start attempts exhausted
        """
        cfg = get_config().get("comfyui", {})
        base_url = cfg.get("baseUrl", "http://127.0.0.1:8188")
        checkpoint_name = cfg.get("checkpoint", "sd_xl_base_1.0.safetensors")

        # Check checkpoint
        checkpoint_available = self._check_checkpoint(cfg, checkpoint_name)
        workflow_available = self._check_workflow(cfg)

        online = self.is_running()
        pid = self._proc.pid if self._proc else None

        if online:
            if checkpoint_available and workflow_available:
                state = "ready"
            else:
                state = "degraded"
            return {
                "available": True,
                "state": state,
                "base_url": base_url,
                "generation_ready": checkpoint_available and workflow_available,
                "workflow_available": workflow_available,
                "checkpoint": checkpoint_name,
                "checkpoint_available": checkpoint_available,
                "owned": self._owned,
                "pid": pid,
                "last_error": self._last_error,
                "error_code": None if state == "ready" else (
                    "CHECKPOINT_MISSING" if not checkpoint_available else
                    "WORKFLOW_MISSING" if not workflow_available else None
                ),
                "health_endpoint": "/system_stats",
            }
        elif self._starting:
            return {
                "available": False,
                "state": "starting",
                "base_url": base_url,
                "generation_ready": False,
                "workflow_available": workflow_available,
                "checkpoint": checkpoint_name,
                "checkpoint_available": checkpoint_available,
                "owned": self._owned,
                "pid": pid,
                "last_error": None,
                "error_code": None,
                "health_endpoint": None,
            }
        elif self._last_error and "exited with code" in str(self._last_error):
            return {
                "available": False,
                "state": "failed",
                "base_url": base_url,
                "generation_ready": False,
                "workflow_available": workflow_available,
                "checkpoint": checkpoint_name,
                "checkpoint_available": checkpoint_available,
                "owned": self._owned,
                "pid": pid,
                "last_error": self._last_error,
                "error_code": "COMFYUI_EXITED",
                "health_endpoint": None,
            }
        else:
            return {
                "available": False,
                "state": "stopped",
                "base_url": base_url,
                "generation_ready": False,
                "workflow_available": workflow_available,
                "checkpoint": checkpoint_name,
                "checkpoint_available": checkpoint_available,
                "owned": self._owned,
                "pid": pid,
                "last_error": self._last_error,
                "error_code": None,
                "health_endpoint": None,
            }

    def ensure_running(self) -> dict[str, Any]:
        """
        Check if ComfyUI is running, start if not.
        Deduplicates: only one start attempt at a time across all threads.
        Idempotent: if already running, returns immediately with launched=False.
        """
        # Fast path: already running
        if self.is_running():
            self._last_error = None  # clear any stale error
            return {"ok": True, "message": "ComfyUI already running", "launched": False,
                    "state": "ready", "pid": self._proc.pid if self._proc else None}

        # If another thread is starting ComfyUI, wait for it
        if self._starting:
            for _ in range(60):
                time.sleep(2)
                if self.is_running():
                    return {"ok": True, "message": "ComfyUI ready after waiting", "launched": False,
                            "state": "ready", "pid": self._proc.pid if self._proc else None}
                if not self._starting:
                    break
            # If still starting after 120s, return starting state
            if self._starting:
                return {"ok": True, "message": "ComfyUI is still starting", "launched": False,
                        "state": "starting", "pid": self._proc.pid if self._proc else None}

        with self._lock:
            # Double-check after acquiring lock
            if self.is_running():
                self._last_error = None
                return {"ok": True, "message": "ComfyUI already running", "launched": False,
                        "state": "ready", "pid": self._proc.pid if self._proc else None}
            # If starting was set while waiting for lock, wait again
            if self._starting:
                for _ in range(60):
                    time.sleep(2)
                    if self.is_running():
                        return {"ok": True, "message": "ComfyUI ready after waiting", "launched": False,
                                "state": "ready", "pid": self._proc.pid if self._proc else None}
                # Starting flag stuck — force reset
                self._starting = False

            self._starting = True
            self._last_error = None
            self._start_attempts += 1
            try:
                self.start()
                self._last_error = None
                return {"ok": True, "message": "ComfyUI started successfully", "launched": True,
                        "state": "ready", "pid": self._proc.pid if self._proc else None}
            except Exception as e:
                self._last_error = str(e)
                return {"ok": False, "message": str(e),
                        "error_code": "COMFYUI_START_FAILED",
                        "state": "failed",
                        "log_path": str(LOGS_DIR / "comfyui-error.log")}
            finally:
                self._starting = False

    def start(self) -> None:
        """Start ComfyUI subprocess. Only starts if 8188 is completely free."""
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        port_free = s.connect_ex(('127.0.0.1', 8188)) != 0
        s.close()
        if not port_free:
            # Port occupied — wait for existing ComfyUI to respond
            for i in range(45):
                time.sleep(2)
                if self.is_running():
                    self._owned = False  # Not ours, we reused
                    return
            raise RuntimeError(
                "Port 8188 occupied but ComfyUI /system_stats unreachable after 90s.\n"
                "Please check the process on port 8188."
            )

        cfg = get_config().get("comfyui", {})

        # Resolve paths
        install_root = cfg.get("installRoot", "")
        python_exe = cfg.get("pythonExe", "")
        main_py = cfg.get("mainPy", "")
        start_script = cfg.get("startScript", "")

        # Auto-discover if not configured (Windows-only)
        if not install_root or not python_exe:
            install_root, python_exe, main_py, start_script = _discover_paths()

        # Write back to config
        _save_paths(install_root, python_exe, main_py, start_script)

        timeout = int(cfg.get("startupTimeoutSec", 180))

        if python_exe and main_py and os.path.exists(python_exe) and os.path.exists(main_py):
            # Direct launch (python_embeded on Windows, system python on Linux)
            cmd = [
                python_exe, "-s", main_py,
                "--listen", "127.0.0.1",
                "--port", "8188",
            ]
            cwd = install_root
        elif start_script and os.path.exists(start_script):
            # Fallback: run batch/shell script
            if os.name == "nt":
                cmd = ["cmd.exe", "/c", start_script]
            else:
                cmd = ["bash", start_script]
            cwd = os.path.dirname(start_script) or install_root
        elif main_py and os.path.exists(main_py):
            # Linux / Cloud Studio: use system python3
            cmd = [
                "python3", "-s", main_py,
                "--listen", "127.0.0.1",
                "--port", "8188",
            ]
            cwd = install_root or os.path.dirname(main_py)
        else:
            raise RuntimeError(
                f"Cannot start ComfyUI: no valid executable found.\n"
                f"python_exe={python_exe} exists={os.path.exists(python_exe) if python_exe else 'N/A'}\n"
                f"main_py={main_py} exists={os.path.exists(main_py) if main_py else 'N/A'}\n"
                f"start_script={start_script}"
            )

        stdout_log = str(LOGS_DIR / "comfyui.log")
        stderr_log = str(LOGS_DIR / "comfyui-error.log")

        try:
            popen_kwargs = {
                "cwd": cwd,
                "stdout": open(stdout_log, "w"),
                "stderr": open(stderr_log, "w"),
                "stdin": subprocess.DEVNULL,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
            self._proc = subprocess.Popen(cmd, **popen_kwargs)
        except Exception as e:
            raise RuntimeError(f"Failed to launch ComfyUI process: {e}")

        self._owned = True

        # Save PID
        _save_pid(self._proc.pid)

        # Wait until ready
        try:
            self.wait_until_ready(timeout)
        except Exception as e:
            self._last_error = str(e)
            # Don't leave a zombie
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                pass
            self._proc = None
            self._owned = False
            raise

    def wait_until_ready(self, timeout_sec: int = 180) -> None:
        """Poll /system_stats until ComfyUI responds or timeout."""
        deadline = time.monotonic() + timeout_sec
        last_error = ""
        while time.monotonic() < deadline:
            if self._proc and self._proc.poll() is not None:
                stderr_path = LOGS_DIR / "comfyui-error.log"
                stderr_tail = ""
                try:
                    with open(stderr_path) as f:
                        lines = f.readlines()
                        stderr_tail = "".join(lines[-5:])
                except Exception:
                    pass
                raise RuntimeError(
                    f"ComfyUI process exited with code {self._proc.returncode}.\n"
                    f"stderr: {stderr_tail}"
                )
            try:
                r = requests.get("http://127.0.0.1:8188/system_stats",
                               timeout=3, proxies={"http": None, "https": None})
                if r.status_code == 200:
                    return
            except Exception as e:
                last_error = str(e)
            time.sleep(2)
        raise RuntimeError(
            f"ComfyUI did not become ready within {timeout_sec}s.\n"
            f"Last error: {last_error}\nLogs: {LOGS_DIR}"
        )

    def stop_if_owned(self) -> None:
        """Stop ComfyUI only if we started it."""
        if self._proc and self._owned:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=10)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
            self._owned = False

    def _check_workflow(self, cfg: dict) -> bool:
        rel = cfg.get("workflowPath", "")
        if not rel:
            return False
        wf_path = Path(__file__).parent.parent.parent / rel
        return wf_path.exists()

    def _check_checkpoint(self, cfg: dict, checkpoint_name: str) -> bool:
        """Check if the required SD checkpoint file exists on disk."""
        if not checkpoint_name:
            return False
        install_root = cfg.get("installRoot", "")
        if not install_root:
            return False
        # Try multiple possible locations
        candidates = [
            Path(install_root) / "ComfyUI" / "models" / "checkpoints" / checkpoint_name,
            Path(install_root) / "models" / "checkpoints" / checkpoint_name,
            Path(install_root) / "ComfyUI" / "models" / "checkpoints" / checkpoint_name.replace(".safetensors", ".ckpt"),
        ]
        for p in candidates:
            if p.exists():
                return True
        return False


# ---- Singleton access ----

def get_comfyui_manager() -> ComfyUIProcessManager:
    return ComfyUIProcessManager.get_instance()


# ---- Internal helpers ----

def _discover_paths() -> tuple[str, str, str, str]:
    """Auto-discover ComfyUI installation paths (Windows + Linux)."""
    candidates = [
        # Windows
        r"G:\ComfyUI_windows_portable",
        r"D:\ComfyUI_windows_portable",
        # Linux / Cloud Studio
        "/workspace/ComfyUI",
        os.path.expanduser("~/ComfyUI"),
    ]
    for root in candidates:
        if not os.path.isdir(root):
            continue
        # Windows: python_embeded
        py = os.path.join(root, "python_embeded", "python.exe")
        main = os.path.join(root, "ComfyUI", "main.py")
        if os.path.exists(py) and os.path.exists(main):
            bat = os.path.join(root, "run_nvidia_gpu.bat")
            return (root, py, main, bat if os.path.exists(bat) else "")
        # Linux: main.py at root level
        main = os.path.join(root, "main.py")
        if os.path.exists(main):
            return (root, "python3", main, "")
    return ("", "", "", "")


def _save_paths(install_root: str, python_exe: str, main_py: str, start_script: str) -> None:
    """Update config.json with discovered paths."""
    if not install_root:
        return
    cfg_path = Path(__file__).parent.parent.parent / "config.json"
    try:
        with open(cfg_path, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        changed = False
        cf = cfg.setdefault("comfyui", {})
        for key, val in [
            ("installRoot", install_root),
            ("pythonExe", python_exe),
            ("mainPy", main_py),
            ("startScript", start_script),
        ]:
            if not cf.get(key) and val:
                cf[key] = val
                changed = True
        if changed:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _save_pid(pid: int) -> None:
    """Save current ComfyUI PID for stop-workbench.ps1."""
    proc_file = LOGS_DIR / "processes.json"
    procs = {}
    try:
        if proc_file.exists():
            procs = json.loads(proc_file.read_text())
    except Exception:
        pass
    procs["comfyui"] = pid
    proc_file.write_text(json.dumps(procs))

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

from app.core.config import get_settings


logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("tinix.cleanup")


def terminate_processes(processes: list[psutil.Process], timeout: float = 3.0) -> int:
    """Gracefully terminate a list of processes and kill if still alive after timeout."""
    if not processes:
        return 0

    killed_count = 0
    unique_procs: dict[int, psutil.Process] = {}
    for p in processes:
        try:
            if p.is_running() and p.pid != os.getpid():
                unique_procs[p.pid] = p
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    for proc in unique_procs.values():
        try:
            for child in proc.children(recursive=True):
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Wait for processes to exit
    all_targets = list(unique_procs.values())
    _, alive = psutil.wait_procs(all_targets, timeout=timeout)

    for proc in alive:
        try:
            for child in proc.children(recursive=True):
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            proc.kill()
            killed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return len(unique_procs)


def cleanup_previous_sessions() -> tuple[int, int]:
    """
    Closes any previous Tinix backend instances and Chrome automation profiles.
    Returns (backend_processes_closed, chrome_processes_closed).
    """
    settings = get_settings()
    current_pid = os.getpid()
    project_dir = settings.project_root.resolve()
    chrome_profile_dir = settings.chrome_profile_dir.resolve()
    target_port = settings.port

    backend_procs: list[psutil.Process] = []
    chrome_procs: list[psutil.Process] = []

    # 1. Close processes bound to the backend port
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == target_port and conn.status == psutil.CONN_LISTEN:
                if conn.pid and conn.pid != current_pid:
                    try:
                        p = psutil.Process(conn.pid)
                        backend_procs.append(p)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
    except Exception:
        pass

    # Windows fallback for port lookup if psutil net_connections was restricted
    if not backend_procs and os.name == "nt":
        try:
            cmd = f"(Get-NetTCPConnection -LocalPort {target_port} -State Listen -ErrorAction SilentlyContinue).OwningProcess"
            output = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", cmd],
                text=True,
                timeout=3,
            )
            for line in output.strip().splitlines():
                pid_str = line.strip()
                if pid_str.isdigit():
                    pid = int(pid_str)
                    if pid != current_pid:
                        try:
                            backend_procs.append(psutil.Process(pid))
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
        except Exception:
            pass

    # 2. Check recorded chrome sessions in data/chrome_sessions.json
    sessions_file = settings.data_dir / "chrome_sessions.json"
    if sessions_file.exists():
        try:
            data = json.loads(sessions_file.read_text(encoding="utf-8"))
            for account_id, info in data.items():
                pid = info.get("pid")
                if pid and pid != current_pid:
                    try:
                        p = psutil.Process(pid)
                        chrome_procs.append(p)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
        except Exception:
            pass

    # 3. Iterate running processes to find Tinix backend and Tinix-managed Chrome instances
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.pid == current_pid:
                continue

            name = (proc.info.get("name") or "").lower()
            cmdline = proc.info.get("cmdline") or []
            cmd_str = " ".join(cmdline).lower()

            # Identify Tinix-owned Chrome (by checking user-data-dir matching chrome_profile_dir)
            if "chrome" in name:
                profile_dir_str = str(chrome_profile_dir).lower()
                if any(profile_dir_str in arg.lower() for arg in cmdline):
                    chrome_procs.append(proc)
                elif "--remote-debugging-port=" in cmd_str and profile_dir_str in cmd_str:
                    chrome_procs.append(proc)

            # Identify old Python backend instances belonging to this project
            elif "python" in name:
                proj_str = str(project_dir).lower()
                is_tinix = False
                if ("app.main:app" in cmd_str or "-m app" in cmd_str or "app/__main__.py" in cmd_str):
                    if proj_str in cmd_str:
                        is_tinix = True
                    else:
                        try:
                            if proj_str in str(proc.cwd()).lower():
                                is_tinix = True
                        except Exception:
                            pass
                if is_tinix:
                    backend_procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    # Terminate identified processes
    num_backend = terminate_processes(backend_procs, timeout=2.5)
    num_chrome = terminate_processes(chrome_procs, timeout=2.5)

    # 4. Clean up sessions file
    if sessions_file.exists():
        try:
            sessions_file.write_text("{}", encoding="utf-8")
        except Exception:
            pass

    # 5. Remove stale Chrome profile locks (SingletonLock, lockfile, etc.)
    if chrome_profile_dir.exists():
        for profile_folder in chrome_profile_dir.iterdir():
            if profile_folder.is_dir():
                for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
                    lock_path = profile_folder / lock_name
                    if lock_path.exists():
                        try:
                            if lock_path.is_file() or lock_path.is_symlink():
                                lock_path.unlink(missing_ok=True)
                        except Exception:
                            pass

    return num_backend, num_chrome


def main() -> None:
    try:
        backends, chromes = cleanup_previous_sessions()
        if backends > 0 or chromes > 0:
            details = []
            if backends > 0:
                details.append(f"{backends} tien trinh backend cu")
            if chromes > 0:
                details.append(f"{chromes} phien Chrome cu")
            logger.info("[Tinix] Da don dep va dong: %s.", ", ".join(details))
        else:
            logger.info("[Tinix] Khong co phien lam viec cu nao ton dong.")
    except Exception as e:
        logger.warning("[Tinix] Bo qua loi kiem tra phien cu: %s", e)


if __name__ == "__main__":
    main()

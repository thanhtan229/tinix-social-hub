from __future__ import annotations

import json
import logging
import os
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


def owns_backend(proc: psutil.Process, project_dir: Path) -> bool:
    try:
        args = proc.cmdline()
        name = proc.name().lower()
        if "python" not in name or Path(proc.cwd()).resolve() != project_dir.resolve():
            return False
        modules = {"app", "app.worker_entry"}
        return any(args[i] == "-m" and args[i + 1] in modules for i in range(len(args) - 1)) or "app.main:app" in args or any(
            Path(arg).resolve() == project_dir.resolve() / "app" / "__main__.py" for arg in args[1:] if arg.endswith("__main__.py")
        )
    except (psutil.Error, OSError, ValueError):
        return False


def owns_chrome(proc: psutil.Process, profile_root: Path) -> bool:
    try:
        if "chrome" not in proc.name().lower():
            return False
        args = proc.cmdline()
        for i, arg in enumerate(args):
            if arg.startswith("--user-data-dir="):
                raw = arg.split("=", 1)[1]
            elif arg == "--user-data-dir" and i + 1 < len(args):
                raw = args[i + 1]
            else:
                continue
            path = Path(raw.strip('"')).resolve()
            root = profile_root.resolve()
            return path == root or root in path.parents
        return False
    except (psutil.Error, OSError, ValueError):
        return False


def cleanup_previous_sessions() -> tuple[int, int]:
    """
    Closes any previous Tinix backend instances and Chrome automation profiles.
    Returns (backend_processes_closed, chrome_processes_closed).
    """
    settings = get_settings()
    current_pid = os.getpid()
    project_dir = settings.project_root.resolve()
    chrome_profile_dir = settings.chrome_profile_dir.resolve()

    backend_procs: list[psutil.Process] = []
    chrome_procs: list[psutil.Process] = []

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
                        if owns_chrome(p, chrome_profile_dir):
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

            if owns_chrome(proc, chrome_profile_dir):
                chrome_procs.append(proc)
            elif owns_backend(proc, project_dir):
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

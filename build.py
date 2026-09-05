from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
from pathlib import Path

# Safe console encoding on Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent


def read_current_version() -> str:
    init_py = PROJECT_ROOT / "app" / "__init__.py"
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init_py.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"Could not find __version__ in {init_py}")
    return match.group(1)


def bump_version_str(current: str, part: str = "patch") -> str:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", current)
    if not match:
        return f"{current}.1"
    major, minor, patch = map(int, match.groups())
    if part == "major":
        return f"{major + 1}.0.0"
    elif part == "minor":
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"


def update_version(new_version: str) -> None:
    init_py = PROJECT_ROOT / "app" / "__init__.py"
    text = init_py.read_text(encoding="utf-8")
    updated = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']', f'__version__ = "{new_version}"', text)
    init_py.write_text(updated, encoding="utf-8")

    # Update docs if applicable
    doc_path = PROJECT_ROOT / "docs" / "HUONG_DAN_SU_DUNG.md"
    if doc_path.exists():
        doc_text = doc_path.read_text(encoding="utf-8")
        doc_updated = re.sub(r"Phiên bản áp dụng:\s*`[^`]+`", f"Phiên bản áp dụng: `{new_version}`", doc_text)
        doc_path.write_text(doc_updated, encoding="utf-8")

    print(f"[Build] Da cap nhat version: v{new_version}")


def generate_ico() -> Path:
    svg_path = PROJECT_ROOT / "app" / "static" / "favicon.svg"
    ico_path = PROJECT_ROOT / "app" / "static" / "favicon.ico"
    if not svg_path.exists():
        raise FileNotFoundError(f"SVG logo not found at {svg_path}")

    try:
        from playwright.sync_api import sync_playwright
        from PIL import Image

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 512, "height": 512})
            page.goto(f"file:///{svg_path.resolve()}")
            png_bytes = page.locator("svg").screenshot(omit_background=True)
            browser.close()

        img = Image.open(io.BytesIO(png_bytes))
        img.save(
            ico_path,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        print(f"[Build] Da tao Windows icon: {ico_path.relative_to(PROJECT_ROOT)} ({ico_path.stat().st_size} bytes)")
    except Exception as exc:
        print(f"[Build] Canh bao: Khong the render .ico tu dong ({exc}). Bo qua buoc nay.")

    return ico_path


def create_desktop_shortcut() -> None:
    if os.name != "nt":
        return

    desktop_script = """
$desktop = [Environment]::GetFolderPath('Desktop')
$ws = New-Object -ComObject WScript.Shell
$shortcutPath = Join-Path $desktop 'Tinix Social Hub.lnk'
$targetPath = '{target}'
$workDir = '{workdir}'
$iconLocation = '{icon}'

$s = $ws.CreateShortcut($shortcutPath)
$s.TargetPath = $targetPath
$s.WorkingDirectory = $workDir
$s.IconLocation = $iconLocation
$s.Description = 'Tinix Social Hub - Studio Quan ly Mang Xa Hoi'
$s.Save()
"""
    vbs_path = PROJECT_ROOT / "START.vbs"
    bat_path = PROJECT_ROOT / "START.bat"
    target = str(vbs_path if vbs_path.exists() else bat_path)
    ico_path = str(PROJECT_ROOT / "app" / "static" / "favicon.ico")

    ps_code = desktop_script.format(
        target=target.replace("'", "''"),
        workdir=str(PROJECT_ROOT).replace("'", "''"),
        icon=f"{ico_path},0".replace("'", "''"),
    )

    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_code],
            check=True,
            capture_output=True,
            text=True,
        )
        print("[Build] Da tao/cap nhat Desktop shortcut: 'Tinix Social Hub.lnk'")
    except Exception as exc:
        print(f"[Build] Canh bao: Khong the tao desktop shortcut ({exc})")


def run_tests() -> bool:
    print("[Build] Dang chay kiem thu tu dong...")
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("[Build] Kiem thu: 100% PASSED!")
        return True
    else:
        print("[Build] LOI: Kiem thu that bai!")
        print(result.stdout[-1000:])
        print(result.stderr[-1000:])
        return False


def git_commit(version: str, message: str | None = None) -> None:
    commit_msg = message or f"build(release): bump version to v{version} and rebuild app"
    try:
        subprocess.run(["git", "add", "."], cwd=PROJECT_ROOT, check=True)
        # Check if there are staged changes
        status = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=PROJECT_ROOT,
        )
        if status.returncode != 0:
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=PROJECT_ROOT, check=True)
            print(f"[Build] Git commit thanh cong: '{commit_msg}'")
        else:
            print("[Build] Git: Khong co thay doi nao de commit.")
    except Exception as exc:
        print(f"[Build] Canh bao: Git commit gap loi: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and release tool for Tinix Social Hub")
    parser.add_argument("--bump", choices=["patch", "minor", "major"], default=None, help="Tu dong tang version")
    parser.add_argument("--version", type=str, default=None, help="Dat dich danh version")
    parser.add_argument("--no-bump", action="store_true", help="Khong thay doi version hien tai")
    parser.add_argument("--no-tests", action="store_true", help="Bo qua kiem thu tu dong")
    parser.add_argument("--no-commit", action="store_true", help="Khong tu dong commit git")
    parser.add_argument("-m", "--message", type=str, default=None, help="Thong diep git commit tuy chon")
    args = parser.parse_args()

    current_version = read_current_version()
    new_version = current_version

    if args.version:
        new_version = args.version
        update_version(new_version)
    elif not args.no_bump:
        bump_part = args.bump or "patch"
        new_version = bump_version_str(current_version, bump_part)
        update_version(new_version)
    else:
        print(f"[Build] Giu nguyen version: v{current_version}")

    # 1. Compile icons
    generate_ico()

    # 2. Update shortcut
    create_desktop_shortcut()

    # 3. Verify tests
    if not args.no_tests:
        if not run_tests():
            sys.exit(1)

    # 4. Commit git
    if not args.no_commit:
        git_commit(new_version, args.message)

    print(f"\n[Build HOAN TAT] Tinix Social Hub v{new_version} da san sang!")


if __name__ == "__main__":
    main()

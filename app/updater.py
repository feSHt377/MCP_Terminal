"""更新检测与自动更新（端用户版，无需 git）。

架构：
- 检测：拉取 raw.githubusercontent.com 上 main 分支的 app/version.py，
  解析远端 __version__ 并与本地比较（纯 HTTPS，可匿名，失败静默）。
- 下载：codeload.github.com 的 main 分支 zip 归档，解压到 .runtime/update/。
- 应用：由独立 helper 进程完成「等旧 GUI 退出 → 替换源码 → 重新拉起 GUI」，
  避免覆盖运行中的文件，也避免「先回包再重启」时 IPC 连接被掐断丢响应。

本模块不依赖 PySide6，可在无 GUI 的 helper 进程中运行。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent

REPO_URL = "https://github.com/feSHt377/MCP_Terminal"
BRANCH = "main"
VERSION_URL = (
    f"https://raw.githubusercontent.com/feSHt377/MCP_Terminal/{BRANCH}/app/version.py"
)
ZIP_URL = f"{REPO_URL}/archive/refs/heads/{BRANCH}.zip"

UPDATE_DIR = PROJECT_ROOT / ".runtime" / "update"
EXTRACT_DIR = UPDATE_DIR / "extracted"
UPDATE_LOG = UPDATE_DIR / "update.log"

# 应用更新时保护的用户数据 / 运行数据顶层路径，绝不覆盖。
# 源码 zip 归档本来就不含它们（.gitignore 已排除），此处为双保险。
PROTECTED_TOPS = {
    ".git",
    ".runtime",
    ".venv",
    "venv",
    "env",
    "logs",
    "__pycache__",
    ".pytest_cache",
    ".vscode",
    ".idea",
    "Template",
    "config.yaml",
}

_UA = {"User-Agent": "mcpterminal-updater"}


def _parse_version(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", text.strip().lstrip("vV"))
    return tuple(int(n) for n in nums) or (0,)


def get_local_version() -> str:
    try:
        from app.version import __version__

        return str(__version__)
    except Exception:
        return "0.0.0"


def _fetch_remote_version(timeout: float = 6.0) -> str | None:
    with urllib.request.urlopen(
        urllib.request.Request(VERSION_URL, headers=_UA), timeout=timeout
    ) as resp:
        text = resp.read().decode("utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    return m.group(1) if m else None


def check_for_update(timeout: float = 6.0) -> dict[str, Any]:
    """检测是否有新版本（不下载、不更新）。"""
    try:
        remote = _fetch_remote_version(timeout)
    except Exception as exc:  # 网络抖动/离线：失败静默
        return {"status": "error", "message": f"无法连接更新源: {exc}"}
    if remote is None:
        return {"status": "error", "message": "无法解析远端版本"}
    local = get_local_version()
    return {
        "status": "success",
        "local": local,
        "remote": remote,
        "has_update": _parse_version(remote) > _parse_version(local),
        "url": REPO_URL,
    }


def download_and_extract(
    timeout: float = 90.0, progress: Callable[[str], None] | None = None
) -> dict[str, Any]:
    """下载最新源码 zip 并解压，校验版本后返回成功。

    返回 ``{"status":"success","remote":..., "source":<解压后的源码目录>}``。
    """
    try:
        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        if progress:
            progress("正在下载更新包…")
        zip_path = UPDATE_DIR / "main.zip"
        with urllib.request.urlopen(
            urllib.request.Request(ZIP_URL, headers=_UA), timeout=timeout
        ) as resp, open(zip_path, "wb") as fh:
            shutil.copyfileobj(resp, fh, length=1 << 16)

        if progress:
            progress("正在解压更新包…")
        if EXTRACT_DIR.exists():
            shutil.rmtree(EXTRACT_DIR, ignore_errors=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(EXTRACT_DIR)

        tops = [p for p in EXTRACT_DIR.iterdir() if p.is_dir()]
        if not tops:
            return {"status": "error", "message": "更新包结构异常"}
        source = tops[0]
        ver_file = source / "app" / "version.py"
        if not ver_file.exists():
            return {"status": "error", "message": "更新包缺少版本文件"}
        m = re.search(
            r'__version__\s*=\s*["\']([^"\']+)["\']',
            ver_file.read_text(encoding="utf-8"),
        )
        remote = m.group(1) if m else None
        if remote is None:
            return {"status": "error", "message": "更新包版本解析失败"}
        if _parse_version(remote) < _parse_version(get_local_version()):
            return {"status": "error", "message": f"更新包版本异常（{remote}）"}
        return {"status": "success", "remote": remote, "source": str(source)}
    except Exception as exc:
        return {"status": "error", "message": f"下载更新失败: {exc}"}


def apply_update_files(source: str) -> dict[str, Any]:
    """把解压后的源码覆盖到项目根目录，跳过受保护路径。"""
    source = Path(source)
    errors: list[str] = []
    applied = 0
    for item in source.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(source)
        if rel.parts and rel.parts[0] in PROTECTED_TOPS:
            continue
        target = PROJECT_ROOT / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            applied += 1
        except Exception as exc:
            errors.append(f"{rel}: {exc}")
    if errors:
        return {"status": "error", "applied": applied, "errors": errors}
    return {"status": "success", "applied": applied}


def spawn_update_helper(gui_pid: int, source: str) -> dict[str, Any]:
    """拉起独立 helper 进程：等 GUI 退出后应用更新并重新启动 GUI。"""
    cmd = [
        sys.executable,
        "-m",
        "app.updater",
        "--apply",
        "--pid",
        str(gui_pid),
        "--source",
        str(source),
    ]
    kwargs: dict[str, Any] = {
        "cwd": str(PROJECT_ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.exists():
            cmd[0] = str(pythonw)
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    return {"status": "success", "helper_pid": proc.pid}


def _launch_gui() -> None:
    cmd = [sys.executable, "-m", "app.main"]
    kwargs: dict[str, Any] = {
        "cwd": str(PROJECT_ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.exists():
            cmd[0] = str(pythonw)
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _run_apply(pid: int, source: str) -> int:
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(UPDATE_LOG, "a", encoding="utf-8") as log:

        def write(*parts: Any) -> None:
            msg = " ".join(str(p) for p in parts)
            print(msg, flush=True)
            log.write(msg + "\n")
            log.flush()

        write("[updater] 等待旧 GUI（pid=%d）退出…" % pid)
        deadline = time.time() + 60
        while time.time() < deadline:
            if not _pid_alive(pid):
                break
            time.sleep(0.3)
        else:
            write("[updater] 等待超时，继续执行")
        write("[updater] 开始应用更新…")
        write("[updater]", json.dumps(apply_update_files(source), ensure_ascii=False))
        write("[updater] 重新启动 GUI…")
        _launch_gui()
        shutil.rmtree(UPDATE_DIR, ignore_errors=True)
        write("[updater] 完成")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    if "--apply" in argv:
        parser = argparse.ArgumentParser(prog="app.updater")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--pid", type=int)
        parser.add_argument("--source")
        args = parser.parse_args(argv)
        if not args.pid or not args.source:
            print("缺少 --pid 或 --source")
            return 2
        return _run_apply(args.pid, args.source)
    print(json.dumps(check_for_update(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

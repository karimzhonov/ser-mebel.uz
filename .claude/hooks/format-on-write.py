import json
import shutil
import subprocess
import sys


def main():
    data = json.load(sys.stdin)
    file_path = (data.get("tool_input") or {}).get("file_path") or (
        data.get("tool_response") or {}
    ).get("filePath")
    if not file_path or not file_path.endswith(".py"):
        return
    if not shutil.which("black") and not shutil.which("ruff"):
        return
    if shutil.which("black"):
        subprocess.run(["black", "-q", file_path], check=False)
    if shutil.which("ruff"):
        subprocess.run(["ruff", "check", "--fix", "-q", file_path], check=False)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass

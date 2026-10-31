"""Package source, documentation, tests and synthetic demo outputs only."""
from __future__ import annotations

from pathlib import Path
import os
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "FinSocratic_课程作业_源码.zip"
FILES = [
    "app.py", "requirements.txt", "requirements-lock.txt", "README.md", "启动研究助手.ps1",
    "OPEN_SOURCE.md", "THIRD_PARTY_COMPONENTS.md", "RESEARCH_PLAN.md",
    "启动应用.bat", ".streamlit/config.toml", "RESEARCH_METHODS.md", "LEARNING_METHODS.md", "NEXT_ACTION.md", "PUBLIC_DATA.md",
]
DIRECTORIES = ["finsocratic", "data/sample", "scripts", "tests", "deliverables", "frontend"]


def main() -> None:
    paths = [ROOT / name for name in FILES]
    for directory in DIRECTORIES:
        for folder, dirs, names in os.walk(ROOT / directory):
            dirs[:] = [name for name in dirs if name not in {"node_modules", "__pycache__", ".git"}]
            paths.extend(Path(folder) / name for name in names)
    paths = sorted(set(p for p in paths if "__pycache__" not in p.parts and "node_modules" not in p.parts and p.suffix not in (".pyc", ".tsbuildinfo")))
    with ZipFile(TARGET, "w", ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, path.relative_to(ROOT))
    print(f"Created {TARGET.name}: {len(paths)} files, {TARGET.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()

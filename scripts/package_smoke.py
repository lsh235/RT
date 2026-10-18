#!/usr/bin/env python3
"""Build a wheel, install it in a fresh venv, and exercise its CLI/assets."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="es-rag-package-smoke-") as temp:
        temp_path = Path(temp)
        wheel_dir = temp_path / "wheel"
        wheel_dir.mkdir()
        source = temp_path / "source"
        source.mkdir()
        shutil.copy2(ROOT / "pyproject.toml", source / "pyproject.toml")
        shutil.copy2(ROOT / "README.md", source / "README.md")
        shutil.copy2(ROOT / "LICENSE", source / "LICENSE")
        shutil.copytree(ROOT / "es_rag_tuner", source / "es_rag_tuner", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        run(sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheel_dir), str(source))
        wheels = list(wheel_dir.glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"expected exactly one wheel, found {len(wheels)}")
        venv_dir = temp_path / "venv"
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run(str(python), "-m", "pip", "install", str(wheels[0]))
        run(str(python), "-m", "es_rag_tuner", "doctor", "--help")
        outside = temp_path / "outside"
        outside.mkdir()
        env = os.environ.copy()
        env["PYTHONPATH"] = ""
        subprocess.run(
            [str(venv_dir / ("Scripts/es-rag-workbench.exe" if os.name == "nt" else "bin/es-rag-workbench")), "doctor", "--help"],
            cwd=outside,
            env=env,
            check=True,
        )
        code = "import importlib.resources as r, es_rag_tuner; assert es_rag_tuner.__version__ == '1.13.0'; assert r.files('es_rag_tuner').joinpath('web/index.html').is_file(); print(es_rag_tuner.__version__)"
        subprocess.run([str(python), "-c", code], cwd=outside, env=env, check=True)


if __name__ == "__main__":
    main()

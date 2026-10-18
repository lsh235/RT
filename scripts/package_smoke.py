#!/usr/bin/env python3
"""Build a wheel, install it in a fresh venv, and exercise its CLI/assets."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DATE_EPOCH = "315532800"  # 1980-01-01T00:00:00Z, the ZIP timestamp floor.


def run(*args: str, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def source_snapshot(destination: Path) -> None:
    destination.mkdir()
    shutil.copy2(ROOT / "pyproject.toml", destination / "pyproject.toml")
    shutil.copy2(ROOT / "README.md", destination / "README.md")
    shutil.copy2(ROOT / "LICENSE", destination / "LICENSE")
    shutil.copytree(
        ROOT / "es_rag_tuner",
        destination / "es_rag_tuner",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    epoch = int(SOURCE_DATE_EPOCH)
    for path in sorted(destination.rglob("*"), reverse=True):
        os.utime(path, (epoch, epoch), follow_symlinks=False)
    os.utime(destination, (epoch, epoch), follow_symlinks=False)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="es-rag-package-smoke-") as temp:
        temp_path = Path(temp)
        build_env = os.environ.copy()
        build_env.update({
            "SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH,
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PIP_NO_CACHE_DIR": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        })
        wheels: list[Path] = []
        for iteration in (1, 2):
            wheel_dir = temp_path / f"wheel-{iteration}"
            source = temp_path / f"source-{iteration}"
            wheel_dir.mkdir()
            source_snapshot(source)
            run(
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-cache-dir",
                "--no-deps",
                "--wheel-dir",
                str(wheel_dir),
                str(source),
                env=build_env,
            )
            built = list(wheel_dir.glob("*.whl"))
            if len(built) != 1:
                raise RuntimeError(f"expected exactly one wheel for build {iteration}, found {len(built)}")
            wheels.append(built[0])
        hashes = [sha256(wheel) for wheel in wheels]
        print(f"wheel SHA-256: {hashes[0]} / {hashes[1]}", flush=True)
        if hashes[0] != hashes[1]:
            raise RuntimeError("identical source snapshots produced different wheel bytes")

        venv_dir = temp_path / "venv"
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run(str(python), "-m", "pip", "install", "--no-cache-dir", "--no-compile", str(wheels[0]), env=build_env)
        run(str(python), "-m", "es_rag_tuner", "doctor", "--help")
        outside = temp_path / "outside"
        outside.mkdir()
        env = os.environ.copy()
        env["PYTHONPATH"] = ""
        subprocess.run(
            [str(venv_dir / ("Scripts/es-rag-workbench.exe" if os.name == "nt" else "bin/es-rag-workbench")), "doctor", "--help"],
            cwd=outside,
            env={**build_env, **env},
            check=True,
        )
        code = "import importlib.metadata as m, importlib.resources as r, es_rag_tuner; assert es_rag_tuner.__version__ == m.version('es-rag-tuning-workbench'); assert r.files('es_rag_tuner').joinpath('web/index.html').is_file(); print(es_rag_tuner.__version__)"
        subprocess.run([str(python), "-c", code], cwd=outside, env={**build_env, **env}, check=True)


if __name__ == "__main__":
    main()

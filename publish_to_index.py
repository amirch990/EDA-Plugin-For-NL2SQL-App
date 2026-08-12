# -*- coding: utf-8 -*-
"""Publish this plugin to the course package index.

    python publish_to_index.py [--index PATH] [--verify]

The index is the same PEP 503 tree the core is served from — one index, many
packages, which is what makes `pip install nl2sql-eda` work the same way
`pip install nl2sql-core` does. A plugin that installs by name rather than by
passing a file around is the difference between an ecosystem and an
attachment.

The gates are the core's, for the same reasons:

    1. clean tree only        a release must be reproducible from a commit
    2. built, then verified   the WHEEL is installed into a fresh venv and
                              its module declaration is loaded from it
    3. no overwrites          a published version is immutable; bump instead

Publishing writes files into the index repo and commits there; pushing is
left to a person.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

REPO = Path(__file__).resolve().parent
PROJECT = "nl2sql-eda"                       # normalised per PEP 503
DEFAULT_INDEX = Path(r"C:\Users\A\dev\nl2sql-core\docs\simple")
REQUIRES_PYTHON = ">=3.10"


def die(msg: str) -> None:
    print(f"\nREFUSED: {msg}")
    raise SystemExit(1)


def run(cmd: list[str], cwd: Path = REPO) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def venv_python(root: Path) -> Path:
    win = root / "Scripts" / "python.exe"
    return win if win.exists() else root / "bin" / "python"


def check_clean_tree() -> None:
    out = run(["git", "status", "--porcelain"]).stdout.strip()
    if out:
        die("the working tree is not committed. A release must be buildable "
            f"from a commit alone.\n\n{out}")


def read_version() -> str:
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version = "([^"]+)"', text, re.M)
    if not m:
        die("no version in pyproject.toml")
    version = m.group(1)
    init = (REPO / "nl2sql_eda" / "__init__.py").read_text(encoding="utf-8")
    m2 = re.search(r'^__version__ = "([^"]+)"', init, re.M)
    if not m2 or m2.group(1) != version:
        die(f"version mismatch: pyproject says {version}, __init__ says "
            f"{m2.group(1) if m2 else 'nothing'}")
    return version


def build(outdir: Path, version: str) -> Path:
    print(f"building {PROJECT} {version} ...")
    p = run([sys.executable, "-m", "build", "--wheel", "--outdir", str(outdir)])
    if p.returncode != 0:
        die(f"build failed:\n{p.stdout}\n{p.stderr}")
    wheels = list(outdir.glob("*.whl"))
    if len(wheels) != 1:
        die(f"expected one wheel, found {len(wheels)}")
    return wheels[0]


VERIFY = """
import importlib.metadata as md, pathlib

# Both entry points must be registered by the WHEEL, not by a source tree.
eps = {ep.name: ep.value for ep in md.entry_points(group="nl2sql.modules")}
assert "eda" in eps, f"the module entry point is missing: {eps}"
pages = {ep.name: ep.value for ep in md.entry_points(group="nl2sql.pages")}
assert "eda" in pages, f"the page entry point is missing: {pages}"

# The built page must have travelled inside the wheel. Checked by PATH, not
# by loading the entry point: loading it would import the parent package,
# which needs a core — and this venv deliberately has none, because what is
# being verified here is the PACKAGING, not the runtime.
dist = md.distribution("nl2sql-eda")
where = pathlib.Path(dist.locate_file("nl2sql_eda/webdist"))
assert (where / "index.html").is_file(), f"no built page at {where}"
assert any(where.rglob("*.js")), "the page ships no javascript"

# And the page hook itself must stay stdlib-only, so it can never add a
# failure of its own on a core we do not control.
src = pathlib.Path(dist.locate_file("nl2sql_eda/page.py")).read_text(encoding="utf-8")
assert "nl2sql_engine" not in src, "page.py imports the engine"

print(f"verify ok: both entry points registered, page present "
      f"({len(list(where.rglob('*')))} files), hook is stdlib-only")
"""


def verify(wheel: Path) -> None:
    print("verifying the built wheel in a fresh venv ...")
    with tempfile.TemporaryDirectory(prefix="edav_") as td:
        root = Path(td) / "venv"
        venv.create(root, with_pip=True)
        py = venv_python(root)
        p = run([str(py), "-m", "pip", "install", "--quiet", "--no-deps",
                 str(wheel)], cwd=Path(td))
        if p.returncode != 0:
            die(f"the built wheel does not install:\n{p.stdout}\n{p.stderr}")
        script = Path(td) / "verify.py"
        script.write_text(VERIFY, encoding="utf-8")
        p = run([str(py), str(script)], cwd=Path(td))
        if p.returncode != 0:
            die(f"the built wheel fails verification:\n{p.stdout}\n{p.stderr}")
        print("  " + p.stdout.strip())


def publish(wheel: Path, version: str, index: Path) -> None:
    project_dir = index / PROJECT
    project_dir.mkdir(parents=True, exist_ok=True)
    target = project_dir / wheel.name
    if target.exists() or list(project_dir.glob(f"*-{version}-*.whl")):
        die(f"{PROJECT} {version} is already published. A published version "
            f"is immutable — bump it instead.")
    shutil.copy2(wheel, target)
    write_project_index(project_dir)
    write_root_index(index)
    print(f"published {wheel.name} -> {target}")

    repo = index.parent.parent                     # …/docs/simple -> repo root
    p = run(["git", "add", str(index)], cwd=repo)
    if p.returncode != 0:
        die(f"git add failed:\n{p.stderr}")
    p = run(["git", "commit", "-m", f"Publish {PROJECT} {version}"], cwd=repo)
    if p.returncode != 0:
        die(f"git commit failed:\n{p.stdout}\n{p.stderr}")
    print(f"committed in {repo}: Publish {PROJECT} {version}")
    print("(nothing is pushed automatically — push when ready)")


def write_project_index(project_dir: Path) -> None:
    rp = REQUIRES_PYTHON.replace(">", "&gt;").replace("<", "&lt;")
    anchors = []
    for whl in sorted(project_dir.glob("*.whl")):
        digest = hashlib.sha256(whl.read_bytes()).hexdigest()
        anchors.append(f'    <a href="{whl.name}#sha256={digest}" '
                       f'data-requires-python="{rp}">{whl.name}</a><br/>')
    (project_dir / "index.html").write_text(
        "<!DOCTYPE html>\n<html>\n  <head>\n"
        '    <meta name="pypi:repository-version" content="1.0">\n'
        f"    <title>Links for {PROJECT}</title>\n  </head>\n  <body>\n"
        f"    <h1>Links for {PROJECT}</h1>\n" + "\n".join(anchors) +
        "\n  </body>\n</html>\n", encoding="utf-8")


def write_root_index(index: Path) -> None:
    """Every project the index serves — regenerated from what is there, so a
    package can never be listed and missing, or present and unlisted."""
    names = sorted(d.name for d in index.iterdir()
                   if d.is_dir() and any(d.glob("*.whl")))
    links = "\n".join(f'    <a href="{n}/">{n}</a><br/>' for n in names)
    (index / "index.html").write_text(
        "<!DOCTYPE html>\n<html>\n  <head>\n"
        '    <meta name="pypi:repository-version" content="1.0">\n'
        "    <title>Simple index</title>\n  </head>\n  <body>\n"
        + links + "\n  </body>\n</html>\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--index", type=Path, default=DEFAULT_INDEX,
                    help=f"the index tree to publish into (default: {DEFAULT_INDEX})")
    ap.add_argument("--verify", action="store_true",
                    help="build and verify only; publish nothing")
    args = ap.parse_args()

    check_clean_tree()
    version = read_version()
    if not args.index.is_dir():
        die(f"no index at {args.index}")

    with tempfile.TemporaryDirectory(prefix="edabuild_") as td:
        wheel = build(Path(td), version)
        verify(wheel)
        if args.verify:
            print("\nverify only — nothing published.")
            return 0
        publish(wheel, version, args.index)

    print(f"\ndone. {PROJECT} {version} is in the index.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

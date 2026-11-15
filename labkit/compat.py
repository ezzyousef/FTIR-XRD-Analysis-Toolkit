"""Versioning, feature flags, deprecation and the consumer contract check.

labkit is vendored: each application carries its own copy, so an application always runs against
one exact labkit version. This module lets it state what it needs and prove it has it:

    from labkit import compat
    compat.require(">=1.2")                    # fail early, with a clear sentence
    if compat.has_feature("virtual_table"): ...
    problems = compat.check_api()              # the vendored copy matches its own manifest
    problems += compat.check_imports("src")    # everything this app imports from labkit is in it

`manifest.json` (next to this file) is the machine-readable contract: every public name per module,
the version it appeared in, the private names applications are known to import (kept stable too),
feature flags and deprecations. `python -m labkit.compat [app folder]` runs both checks.

Policy (semantic versioning): a name in the manifest is removed only in a major version, after
at least one minor version in which using it raised DeprecationWarning naming its replacement.
"""
from __future__ import annotations

import ast
import functools
import importlib
import json
import re
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "manifest.json"
MANIFEST_FORMAT = 1


class Incompatible(RuntimeError):
    """The vendored labkit does not satisfy what the application asked for."""


def manifest(package_dir: Path | None = None) -> dict:
    path = (Path(package_dir) if package_dir else HERE) / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("manifest") != MANIFEST_FORMAT:
        raise Incompatible(f"{path} uses manifest format {data.get('manifest')}; this labkit reads {MANIFEST_FORMAT}")
    return data


def version() -> str:
    from . import __version__
    return __version__


def parse(text: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?\s*", text or "")
    if not m:
        raise ValueError(f"not a version: {text!r}")
    return tuple(int(x or 0) for x in m.groups())  # type: ignore[return-value]


def satisfies(spec: str, have: str | None = None) -> bool:
    """Comma-separated clauses: '>=1.2', '>=1.2,<2', '==1.2.0', '~=1.2' (same major, at least 1.2)."""
    got = parse(have or version())
    for clause in [c.strip() for c in spec.split(",") if c.strip()]:
        m = re.fullmatch(r"(>=|<=|==|!=|~=|>|<)\s*(.+)", clause)
        if not m:
            raise ValueError(f"not a version requirement: {clause!r}")
        op, want = m.group(1), parse(m.group(2))
        ok = {">=": got >= want, "<=": got <= want, "==": got == want, "!=": got != want, ">": got > want,
              "<": got < want, "~=": got >= want and got[0] == want[0]}[op]
        if not ok:
            return False
    return True


def require(spec: str) -> None:
    if not satisfies(spec):
        raise Incompatible(f"This application needs labkit {spec}, but its vendored copy is {version()}. "
                           "Refresh it with labkit's sync.py.")


def features() -> dict[str, str]:
    """Feature name -> the labkit version that introduced it."""
    return dict(manifest().get("features", {}))


def has_feature(name: str) -> bool:
    return name in manifest().get("features", {})


def deprecated(since: str, removal: str, instead: str):
    """Mark a function or class as deprecated. It keeps working and warns once per call site."""
    def wrap(obj):
        message = (f"{obj.__module__}.{obj.__qualname__} is deprecated since labkit {since} and will be "
                   f"removed in {removal}. Use {instead} instead.")

        @functools.wraps(obj)
        def inner(*args, **kwargs):
            warnings.warn(message, DeprecationWarning, stacklevel=2)
            return obj(*args, **kwargs)
        inner.__labkit_deprecated__ = {"since": since, "removal": removal, "instead": instead}
        return inner
    return wrap


# ------------------------------------------------------------------------- contract checks
def public_names(module) -> set[str]:
    """Names a module defines itself (not re-exports) that do not start with an underscore,
    plus public constants written in capitals."""
    out = set()
    for name, value in vars(module).items():
        if name.startswith("_"):
            continue
        home = getattr(value, "__module__", None)
        if home == module.__name__ and (callable(value) or isinstance(value, type)):
            out.add(name)
        elif name.isupper() and not callable(value) and not isinstance(value, type(sys)):
            out.add(name)
    return out


def check_api(package_dir: Path | None = None, *, include_qt: bool = True) -> list[str]:
    """Problems between a labkit copy and its own manifest: missing modules or names, and public
    names that are not declared. An empty list means the copy is complete and fully declared.

    `package_dir` is the folder that *contains* the `labkit` package (default: this copy).
    """
    root = Path(package_dir) if package_dir else HERE.parent
    try:
        data = manifest(root / "labkit")
    except (OSError, ValueError, Incompatible) as e:
        return [f"manifest unreadable: {e}"]
    problems = []
    init = (root / "labkit" / "__init__.py").read_text(encoding="utf-8")
    declared = re.search(r'__version__ = "([^"]+)"', init)
    if not declared or declared.group(1) != data.get("labkit"):
        problems.append(f"version mismatch: __init__ says {declared.group(1) if declared else '?'}, "
                        f"manifest says {data.get('labkit')}")
    own = root.resolve() == HERE.parent.resolve()
    for mod_name, info in data.get("modules", {}).items():
        if info.get("qt") and not include_qt:
            continue
        if not own:  # another copy: check the source text, never import someone else's code
            file = root / (mod_name.replace(".", "/") + ".py")
            if not file.exists():
                file = root / mod_name.replace(".", "/") / "__init__.py"
            if not file.exists():
                problems.append(f"{mod_name}: module file missing")
                continue
            defined = _defined_names(file)
            wanted = set(info.get("symbols", {})) | set(data.get("frozen_private", {}).get(mod_name, []))
            problems += [f"{mod_name}.{n}: declared in the manifest but not defined" for n in sorted(wanted - defined)]
            continue
        try:
            module = importlib.import_module(mod_name)
        except ImportError as e:
            if info.get("qt") and "PySide6" in str(e):
                continue  # Qt not installed here: Qt modules cannot be checked
            problems.append(f"{mod_name}: cannot be imported ({e})")
            continue
        wanted = set(info.get("symbols", {}))
        have = public_names(module)
        problems += [f"{mod_name}.{n}: declared in the manifest but missing" for n in sorted(wanted - have)
                     if not hasattr(module, n)]
        problems += [f"{mod_name}.{n}: public but not declared in manifest.json (add it with a 'since' version)"
                     for n in sorted(have - wanted)]
        for n in data.get("frozen_private", {}).get(mod_name, []):
            if not hasattr(module, n):
                problems.append(f"{mod_name}.{n}: private name that applications import is missing")
    return problems


def _defined_names(file: Path) -> set[str]:
    tree = ast.parse(file.read_text(encoding="utf-8"))
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            out |= {t.id for t in targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.ImportFrom):  # re-exports are available from this module too
            out |= {(a.asname or a.name) for a in node.names}
    return out


SKIP_DIRS = {"labkit", "labkit_issuer", ".git", ".venv", "venv", "node_modules", "build", "dist", "__pycache__"}


def imports_of(root: Path) -> dict[str, set[str]]:
    """What an application's own source imports from labkit: module -> names ('*' = the module itself)."""
    used: dict[str, set[str]] = {}
    for file in Path(root).rglob("*.py"):
        if SKIP_DIRS & set(file.relative_to(root).parts[:-1]):
            continue
        try:
            tree = ast.parse(file.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and (node.module == "labkit" or node.module.startswith("labkit.")):
                used.setdefault(node.module, set()).update(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "labkit" or a.name.startswith("labkit."):
                        used.setdefault(a.name, set()).add("*")
    return used


def check_imports(app_root: Path, package_dir: Path | None = None) -> list[str]:
    """Names an application imports from labkit that the given labkit copy does not provide.
    This is the consumer contract test: run it in the application's test suite and before a sync."""
    data = manifest((Path(package_dir) / "labkit") if package_dir else None)
    modules = data.get("modules", {})
    problems = []
    for mod, names in sorted(imports_of(Path(app_root)).items()):
        if mod == "labkit":
            for n in sorted(names - {"*"}):
                if f"labkit.{n}" not in modules and n != "__version__":
                    problems.append(f"labkit.{n}: no such module in labkit {data.get('labkit')}")
            continue
        if mod not in modules:
            problems.append(f"{mod}: no such module in labkit {data.get('labkit')}")
            continue
        allowed = set(modules[mod].get("symbols", {})) | set(data.get("frozen_private", {}).get(mod, []))
        gone = data.get("removed", {}).get(mod, {})
        for n in sorted(names - {"*"} - allowed):
            hint = f" (removed in {gone[n]['in']}; use {gone[n]['instead']})" if n in gone else ""
            problems.append(f"{mod}.{n}: not provided by labkit {data.get('labkit')}{hint}")
    return problems


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    print(f"labkit {version()}  features: {', '.join(sorted(features())) or '(none)'}")
    problems = check_api()
    for app in argv:
        problems += [f"[{app}] {p}" for p in check_imports(Path(app))]
    for p in problems:
        print("  problem:", p)
    print("contract OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

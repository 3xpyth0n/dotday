"""Utilities for discovering and registering setter plugins.

This module uses the AST to extract a top-level `PLUGIN` literal from
plugin files without executing them. It exposes helpers to discover
plugins, parse metadata, register plugin-specific argparse options,
and generate a help epilog listing available plugins.

PLUGIN schema (example):
PLUGIN = {
    "name": "swww",
    "description": "Set wallpaper using swww",
    "options": [
        {"flags": ["--namespace"], "kwargs": {"help": "Wayland namespace", "type": "str"}}
    ],
    "check_bins": ["swww"]
}
"""

from __future__ import annotations

import ast
import argparse
import logging
import importlib.util as _il
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


# map string type names to actual types for plugin option parsing
TYPE_MAP = {"str": str, "int": int, "float": float, "bool": bool}


@dataclass
class PluginInfo:
    name: str
    description: str
    path: Path
    options: List[Dict[str, Any]]
    check_bins: List[str]


def _literal_from_assign(node: ast.Assign) -> Optional[Any]:
    try:
        return ast.literal_eval(node.value)
    except Exception:
        logging.debug(
            "_literal_from_assign: ast.literal_eval failed for node: %s",
            getattr(node, "lineno", None),
        )
        return None


def parse_plugin_metadata(path: Path) -> Optional[Dict[str, Any]]:
    """Parse top-level PLUGIN literal from `path` without executing the file.

    Returns a dict if found, otherwise None. If no PLUGIN literal exists,
    returns None (caller may fallback to docstring).
    """
    try:
        src = path.read_text()
    except Exception as exc:
        logging.debug("parse_plugin_metadata: failed to read %s: %s", path, exc)
        return None
    try:
        tree = ast.parse(src)
    except Exception as exc:
        logging.debug("parse_plugin_metadata: ast.parse failed for %s: %s", path, exc)
        return None

    # Look for assignment to PLUGIN
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PLUGIN":
                    val = _literal_from_assign(node)
                    if isinstance(val, dict):
                        return val
    return None


def discover_plugins(script_dir: Path) -> List[PluginInfo]:
    sdir = script_dir / "setters"
    out: List[PluginInfo] = []
    if not sdir.exists():
        return out
    for p in sorted(sdir.glob("*.py")):
        if p.name == "__init__.py":
            continue
        # ignore internal helper modules stored in this package
        if p.stem.startswith("plugin_"):
            continue
        meta = parse_plugin_metadata(p)
        desc = ""
        options: List[Dict[str, Any]] = []
        check_bins: List[str] = []
        if meta:
            desc = str(meta.get("description") or "")
            options = list(meta.get("options") or [])
            check_bins = list(meta.get("check_bins") or [])
        else:
            # fallback to module docstring (use AST to get docstring)
            try:
                src_text = p.read_text()
                tree = ast.parse(src_text)
                doc = ast.get_docstring(tree) or ""
                desc = doc.splitlines()[0] if doc else ""
            except Exception:
                desc = ""

        out.append(
            PluginInfo(
                name=p.stem,
                description=desc,
                path=p,
                options=options,
                check_bins=check_bins,
            )
        )
    return out


def register_plugin_args(
    parser: argparse.ArgumentParser, plugin_meta: Dict[str, Any]
) -> None:
    """Register plugin-specific options into `parser`.

    `plugin_meta` should follow the `PLUGIN` schema described above.
    The `type` in kwargs must be one of the strings: 'str','int','float','bool'.
    """
    for opt in plugin_meta.get("options", []) or []:
        flags = opt.get("flags") or []
        kwargs = dict(opt.get("kwargs") or {})
        # map string type names to actual types when provided
        if "type" in kwargs and isinstance(kwargs["type"], str):
            tname = kwargs["type"]
            kwargs["type"] = TYPE_MAP.get(tname, str)
        try:
            parser.add_argument(*flags, **kwargs)
        except Exception as exc:
            logging.debug(
                "register_plugin_args: failed to add option %s: %s", flags, exc
            )
            # best-effort: skip invalid option entries
            continue


def generate_plugins_help(script_dir: Path) -> str:
    """Generate a help epilog string listing all discovered plugins and their options."""
    plugins = discover_plugins(script_dir)
    if not plugins:
        return ""
    lines: List[str] = ["Plugins:"]
    for p in plugins:
        lines.append(f"  {p.name}: {p.description}")
        for opt in p.options:
            flags = ", ".join(opt.get("flags") or [])
            help_text = (opt.get("kwargs") or {}).get("help", "")
            lines.append(f"    {flags} — {help_text}")
    return "\n".join(lines)


def validate_plugin_ast(path: Path) -> List[str]:
    """Return list of imported module names found in plugin AST."""
    try:
        src = path.read_text()
    except Exception as exc:
        logging.debug("validate_plugin_ast: failed to read %s: %s", path, exc)
        return []
    try:
        tree = ast.parse(src)
    except Exception as exc:
        logging.debug("validate_plugin_ast: ast.parse failed for %s: %s", path, exc)
        return []
    names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                names.append(n.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


def load_plugin(script_dir: Path, name: str, allowed_prefixes: Optional[tuple] = None):
    """Load a setter plugin module safely from `script_dir/setters/<name>.py`.

    Performs AST import inspection and rejects plugins that import forbidden
    third-party modules (unless available on the system). Returns the loaded
    module object which must expose a callable `apply(image_path: str)`.
    """
    sdir = script_dir / "setters"
    target = sdir / f"{name}.py"
    if not target.exists():
        avail = [p.stem for p in sorted(sdir.glob("*.py"))] if sdir.exists() else []
        raise FileNotFoundError(f"setter plugin '{name}' not found; available: {avail}")

    imports = validate_plugin_ast(target)

    default_allowed = (
        "os",
        "sys",
        "subprocess",
        "pathlib",
        "time",
        "shutil",
        "platform",
        "logging",
        "re",
        "json",
        "math",
    )
    allowed = allowed_prefixes or default_allowed

    forbidden: List[str] = []

    def _is_stdlib_module(module_name: str) -> bool:
        root = module_name.split(".")[0]
        try:
            # Prefer the stdlib module names set available in recent Python
            if hasattr(sys, "stdlib_module_names"):
                return root in sys.stdlib_module_names
        except Exception:
            pass
        try:
            spec = _il.find_spec(root)
            if spec is None:
                return False
            origin = getattr(spec, "origin", None)
            if origin is None:
                # built-in module
                return True
            stdlib_path = sysconfig.get_paths().get("stdlib")
            if stdlib_path and str(origin).startswith(str(stdlib_path)):
                return True
        except Exception:
            return False
        return False

    seen_roots = set()
    for im in imports:
        if not im:
            continue
        # Consider only the root module for decisions
        root = im.split(".")[0]
        if root in seen_roots:
            continue
        seen_roots.add(root)

        if any(root == p or root.startswith(p + ".") for p in allowed):
            continue
        if _is_stdlib_module(root):
            continue
        try:
            spec = _il.find_spec(root)
            if spec is None:
                forbidden.append(root)
        except Exception as exc:
            logging.debug("load_plugin: find_spec failed for %s: %s", root, exc)
            forbidden.append(root)

    if forbidden:
        # Provide a clearer, actionable error message listing missing modules
        suggestions = []
        for mod in forbidden:
            root = mod.split(".")[0]
            suggestions.append(f"pip install {root}")
        raise RuntimeError(
            f"setter plugin imports forbidden or missing modules: {forbidden}. "
            f"Install missing modules or adjust plugin imports. Suggestions: {'; '.join(suggestions)}"
        )

    spec = _il.spec_from_file_location(f"dotday.setters.{name}", str(target))
    mod = _il.module_from_spec(spec)
    loader = spec.loader
    if loader is None:
        raise RuntimeError("failed to load plugin loader")
    try:
        loader.exec_module(mod)
    except Exception as exc:
        logging.debug("load_plugin: exec_module failed for %s: %s", target, exc)
        raise

    if not hasattr(mod, "apply"):
        raise RuntimeError(
            f"setter plugin '{name}' does not define required function apply(image_path: str)"
        )
    if not callable(getattr(mod, "apply")):
        raise RuntimeError(f"setter plugin 'apply' is not callable")

    return mod

"""Simple sanity check utility for dotday repository.

Usage: python tools/sanity_check.py

Prints discovered plugins and their metadata, and lists AST imports found in each plugin.
"""
from pathlib import Path
import logging
import sys

from setters import plugin_api


def main():
    script_dir = Path(__file__).resolve().parents[1]
    logging.basicConfig(level=logging.INFO)
    plugins = plugin_api.discover_plugins(script_dir)
    if not plugins:
        print("No plugins found under setters/")
        return
    print("Discovered plugins:")
    for p in plugins:
        print(f" - {p.name}: {p.description} (path: {p.path})")
        meta = plugin_api.parse_plugin_metadata(p.path) or {}
        print(f"   options: {meta.get('options')}")
        print(f"   check_bins: {meta.get('check_bins')}")
        imports = plugin_api.validate_plugin_ast(p.path)
        print(f"   ast_imports: {imports}")


if __name__ == "__main__":
    main()

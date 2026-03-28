from pathlib import Path
import json
import logging


def load_catalog(script_dir: Path, language: str = "en") -> dict:
    i18n_dir = script_dir / "i18n"
    path = i18n_dir / f"{language}.json"
    if not path.exists():
        # fallback to english
        path = i18n_dir / "en.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            months = data.get("months", [])
            days = data.get("days", [])
            return {"months": months, "days": days}
    except Exception as exc:
        logging.debug("i18n.load_catalog: failed to load %s: %s", path, exc)
        return {"months": [], "days": []}

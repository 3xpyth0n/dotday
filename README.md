DotDay — a minimal dynamic wallpaper that shows the current month and day as a dot grid.

![License](https://img.shields.io/badge/license-AGPL--3.0-blue) ![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python)

<p align="center"><img src="assets/preview.gif" alt="preview" /></p>

What's this

- Minimal, stylish wallpaper that doubles as a tiny dynamic calendar: a clean dot grid that highlights today.
- Ultra‑customizable: colors, fonts, grid size and rendering options make it yours.
- Lightweight and scriptable — renders one PNG per run and pairs with small "setter" plugins to apply it to your desktop.

Quick start

Install (optional):

```bash
pip install --user .
```

Render and apply now:

```bash
python dotday.py --apply
```

Render without applying:

```bash
python dotday.py --dry-run
```

Common commands

- `python dotday.py run` — render (add `--apply` to set wallpaper)
- `python dotday.py install` — install user timer (systemd user)
- `python dotday.py uninstall` — remove timer

Flags you’ll use most

- `-o/--output` — write the rendered PNG to this path (default: `~/.cache/dotday/wallpaper.png`). Accepts absolute paths or `~` expansion; parent directories are created when possible.
- `--date YYYY-MM-DD` — render for a specific date
- `--setter NAME` — override configured setter plugin
- `--resolution WxH` — custom output size (e.g. `1920x1080`)
- `--color-bg`, `--color-today`, `--color-past`, `--color-remaining` — temporary color overrides

Configuration & plugins

- Start from [config.toml.example](config.toml.example) for all options.
- Setter plugins live in `setters/`. See [SETTER_PLUGIN.md](SETTER_PLUGIN.md) for how to add one.

Dependencies & notes

- Python 3.11+ recommended. Rendering requires `Pillow`; `numpy` is optional but improves gradients.
- The `install` command configures a systemd user timer; make sure `systemd --user` is available on your platform.
- In CI or non-interactive checks set `DOTDAY_CI=1` so `--check` tolerates missing system services.

Contributing

- Want a new setter? Read [SETTER_PLUGIN.md](SETTER_PLUGIN.md) and drop a module in `setters/`.

License

AGPL-3.0 — see [LICENSE](LICENSE).

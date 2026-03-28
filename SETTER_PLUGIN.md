# Setter Plugin Schema

Note: DotDay discovers any Python file added under the `setters/` directory
and will expose it via `dotday setters` and register its declared `PLUGIN`
metadata. Adding a new setter does not require editing other repository
files — just add the module and include the `PLUGIN` literal and `apply()`.

Each setter plugin is a Python file placed in the `setters/` directory.
For `dotday` to automatically discover a plugin and expose its options
on the command line, add a Python `PLUGIN` literal at the top of the
file: it will be read via AST without executing the plugin.

Minimal example of `PLUGIN`:

PLUGIN = {
"name": "mytool",
"description": "Set wallpaper using mytool",
"options": [
{"flags": ["--namespace"], "kwargs": {"help": "Wayland namespace", "type": "str"}}
],
"check_bins": ["mytool"],
}

Fields:

- `name` (str): plugin identifier (usually the filename without `.py`).
- `description` (str): short description shown by `dotday setters`.
- `options` (list): list of CLI options specific to the plugin. Each entry contains:
  - `flags`: list of flags (e.g. `["--namespace"]` or `["-n","--namespace"]`).
  - `kwargs`: dictionary of arguments accepted by `argparse.add_argument`.
    The `type` value can be one of `"str"`, `"int"`, `"float"`, `"bool"`.
- `check_bins` (list): binaries to check in PATH when using `--check` (e.g. `["swww"]`).

Important: the top-level `PLUGIN` literal must be a static literal parsable by
`ast.literal_eval()` (no executable expressions or dynamic code). The plugin
metadata is read via AST without executing plugin code.

Compatibility:

- If `PLUGIN` is missing, `dotday` falls back to the module docstring (description line).
- The runtime always calls the module's `apply(image_path: str)` function to set the wallpaper;
  this contract does not change.

Full example of a plugin (`setters/mytool.py`):

PLUGIN = {
"name": "mytool",
"description": "Use mytool to set wallpaper",
"options": [{"flags": ["--quality"], "kwargs": {"help": "JPEG quality", "type": "int", "default": 85}}],
"check_bins": ["mytool"],
}

def apply(image_path: str) -> None: # Local implementation: call the binary or manipulate config
pass

## Adding a CLI option for a plugin

To expose a new CLI option related to a plugin, modify the plugin file
and add the corresponding entry in `PLUGIN["options"]`. `dotday` will
automatically load the option and handle it during argument parsing.

Note: Adding a new setter does not require editing other repository files — just add the module and include the `PLUGIN` literal and `apply()`.

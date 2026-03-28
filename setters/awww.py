"""awww setter plugin

Uses the `awww` command (preferred for Hyprland). Starts daemon if needed.
Only uses stdlib and subprocess; raises clear errors if `awww` is missing.
"""

PLUGIN = {
    "name": "awww",
    "description": "Set wallpaper using awww",
    "options": [
        {
            "flags": ["--namespace"],
            "kwargs": {"help": "Wayland namespace to use", "type": "str"},
        }
    ],
    "check_bins": ["awww"],
}

import os
import subprocess
import time
from setters.plugin_utils import which_bin, start_daemon, is_process_running


def _has_awww() -> bool:
    return which_bin("awww") is not None


def _start_daemon_for_namespace(ns: str | None) -> None:
    # Prefer the dedicated daemon binary if available
    daemon_bin = which_bin("awww-daemon") or which_bin("awww")
    if daemon_bin is None:
        return
    if os.path.basename(daemon_bin) == "awww-daemon":
        args = [daemon_bin]
        if ns:
            args.extend(["--namespace", ns])
    else:
        args = [daemon_bin, "daemon"]
        if ns:
            args.extend(["--namespace", ns])
    start_daemon(args, wait_s=0.8)


def apply(image_path: str) -> None:
    client = which_bin("awww")
    if client is None:
        raise RuntimeError(
            "awww client not found on PATH; install it or choose another setter plugin"
        )
    cmd = [client, "img", image_path]

    # Determine namespace and socket presence
    uid = os.environ.get("UID") or str(os.getuid())
    run_user = f"/run/user/{uid}"

    from setters.plugin_utils import extract_namespace_from_socket

    wayland_ns = os.environ.get("WAYLAND_DISPLAY")
    namespaces = [wayland_ns] if wayland_ns else []
    namespaces.extend(["wayland-0", "wayland-1", "wayland-2"])
    tried = []
    # Prefer to detect an existing awww-daemon socket and use its namespace.
    # Do not attempt a bare client call first to avoid mismatched socket lookups.
    for ns in namespaces:
        if not ns:
            continue
        tried.append(ns)
        # check for an existing socket matching the namespace
        try:
            entries = os.listdir(run_user)
        except Exception:
            entries = []
        sock_matches = [e for e in entries if e.startswith(f"{ns}-awww")]
        # also consider sockets with namespace suffixes
        if not sock_matches:
            suff_matches = [e for e in entries if "awww-daemon" in e]
            for s in suff_matches:
                extracted = extract_namespace_from_socket(s)
                if extracted == ns:
                    sock_matches.append(s)
        if not sock_matches:
            # try starting daemon for this namespace
            _start_daemon_for_namespace(ns)
            try:
                entries = os.listdir(run_user)
            except Exception:
                entries = []
            sock_matches = [e for e in entries if e.startswith(f"{ns}-awww")]
        if sock_matches:
            # call client with explicit namespace
            try:
                subprocess.run(cmd + ["--namespace", ns], check=True)
                return
            except subprocess.CalledProcessError:
                continue

    # Final attempt without namespace
    _start_daemon_for_namespace(None)
    try:
        subprocess.run(cmd, check=True)
        return
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"awww failed after trying namespaces {tried}: {exc}")

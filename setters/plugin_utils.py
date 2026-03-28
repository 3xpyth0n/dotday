from shutil import which
import subprocess
import time
from typing import List


def which_bin(name: str) -> str | None:
    """Return full path to executable `name` or None."""
    try:
        return which(name)
    except Exception:
        return None


def is_process_running(pattern: str) -> bool:
    """Return True if a process matching `pattern` is running (uses pgrep -f)."""
    try:
        p = subprocess.run(["pgrep", "-f", pattern], capture_output=True)
        return p.returncode == 0
    except Exception:
        return False


def start_daemon(args: List[str], wait_s: float = 0.6) -> bool:
    """Start a daemon process with `args` (list) and sleep `wait_s` seconds.

    Returns True on (attempted) start, False on immediate failure.
    """
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(wait_s)
        return True
    except Exception:
        return False


def extract_namespace_from_socket(fname: str) -> str | None:
    """Extract a possible awww namespace from a socket filename.

    Matches logic used by `awww.py`: returns the penultimate part when
    the filename contains 'awww-daemon' and has dots separating namespace.
    """
    try:
        if "awww-daemon" not in fname:
            return None
        if "." in fname:
            parts = fname.split(".")
            for p in reversed(parts[:-1]):
                if p and not p.endswith("sock"):
                    return p
    except Exception:
        return None
    return None

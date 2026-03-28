from pathlib import Path
import sys

# Ensure project root is on sys.path so tests can import local modules
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

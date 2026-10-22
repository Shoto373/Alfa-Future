"""Make `python -m pytest backend/tests` work from the repository root."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

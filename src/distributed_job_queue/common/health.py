"""Process progress markers for container liveness checks."""

import os
from pathlib import Path


def mark_progress():
    path = os.environ.get("PROCESS_HEALTH_FILE")
    if path:
        Path(path).touch()

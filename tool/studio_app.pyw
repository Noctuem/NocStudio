"""Starts the Studio app with no console window. The Start menu's "Studio" runs this."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from studiolib import app  # noqa: E402

sys.exit(app.main())

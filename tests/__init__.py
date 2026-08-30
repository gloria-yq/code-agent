"""Test package configuration."""

import tempfile
from pathlib import Path

_TEST_TEMP = Path(__file__).parent / ".tmp"
_TEST_TEMP.mkdir(exist_ok=True)
tempfile.tempdir = str(_TEST_TEMP)

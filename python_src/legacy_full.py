"""Re-export symbols from original main.py so old imports keep working.
This file will shrink as real implementations move to python_src packages."""
from importlib import import_module
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

legacy_mod = import_module("main")

globals().update({k: v for k, v in vars(legacy_mod).items() if not k.startswith("__")}) 
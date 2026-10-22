"""Enables `python3 -m awg_mesh ...` as an alternative to bin/awg-mesh."""
import sys

from .cli import main

sys.exit(main())

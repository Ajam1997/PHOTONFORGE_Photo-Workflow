"""PyInstaller entry point for the frozen photo-workflow executable.

Mirrors the console_script pip generates from pyproject.toml's
[project.scripts] verbatim, so freezing this produces the same behavior as
the installed CLI. Kept as a real file (not generated at build time) so the
frozen build is reproducible without depending on a particular venv's shim.
"""
import sys

from photo_workflow.pipeline import main

if __name__ == "__main__":
    sys.argv[0] = sys.argv[0].removesuffix(".exe")
    sys.exit(main())

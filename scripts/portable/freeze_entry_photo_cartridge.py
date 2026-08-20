"""PyInstaller entry point for the frozen photo-cartridge executable.

See freeze_entry_photo_workflow.py for why this mirrors the pip-generated
console_script rather than being invoked directly.
"""
import sys

from photo_workflow.cartridge import main

if __name__ == "__main__":
    sys.argv[0] = sys.argv[0].removesuffix(".exe")
    sys.exit(main())

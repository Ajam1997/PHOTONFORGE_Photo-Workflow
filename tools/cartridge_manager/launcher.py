"""Standalone launcher for the Cartridge Manager.

This is the PyInstaller entry point — it adds the src/ path so
photo_workflow imports work, then starts the Tkinter app.
"""

import sys
from pathlib import Path


def main() -> None:
    # When running from source, add src/ to path for photo_workflow imports
    src_dir = Path(__file__).resolve().parent.parent.parent / "src"
    if src_dir.is_dir() and str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    # When frozen (PyInstaller), the hidden imports handle this
    from tools.cartridge_manager.app import CartridgeManagerApp
    import tkinter as tk

    initial = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    root = tk.Tk()
    CartridgeManagerApp(root, initial_path=initial)
    root.mainloop()


if __name__ == "__main__":
    main()

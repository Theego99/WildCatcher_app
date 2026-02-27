"""
Runtime hook for PyInstaller: ensures torch DLLs can find each other on Windows.
This runs BEFORE detector_animales_diego.py, so the DLL paths are set up
before 'import torch' happens.
"""
import os
import sys

if sys.platform == 'win32' and getattr(sys, 'frozen', False):
    # In one-folder mode: sys._MEIPASS = <app>/_internal
    # In one-file mode:   sys._MEIPASS = temp extraction folder
    base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))

    # Add every directory containing .dll files to the search path
    for root, dirs, files in os.walk(base):
        if any(f.endswith('.dll') for f in files):
            try:
                os.add_dll_directory(root)
            except OSError:
                pass
            # Also add to PATH as fallback for older Windows
            os.environ['PATH'] = root + os.pathsep + os.environ.get('PATH', '')

"""Entry point (used by PyInstaller and for running from source without a console)."""
import sys

from alive.app import main

if __name__ == "__main__":
    sys.exit(main())

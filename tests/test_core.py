"""Selbsttest der Kernlogik (wird auch im GitHub-Actions-Build ausgefuehrt)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.core.selftest import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(0 if run() else 1)

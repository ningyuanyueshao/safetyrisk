#!/usr/bin/env python3

"""Stable entry point for the unified L2/pipeline evaluation runner."""

import subprocess
import sys

from run_l3_evaluation import main


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[evaluation] ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

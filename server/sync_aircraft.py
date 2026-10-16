#!/usr/bin/env python3
"""兼容入口：等同 sync_open_data.py --only-aircraft。"""
import sys

import sync_open_data

if __name__ == "__main__":
    sys.exit(sync_open_data.main(["--only-aircraft", *sys.argv[1:]]))

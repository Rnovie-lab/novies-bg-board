#!/bin/bash
pkill -f bgboard_server.py 2>/dev/null
sleep 1
cd "$(dirname "$0")"
find . -name "*.pyc" -delete 2>/dev/null
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
python3 bgboard_server.py

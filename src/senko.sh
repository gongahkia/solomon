#!/bin/bash

# checks for existence of senko directory and creates one if it doesn't exist
if [ -d ~/.config/senko ]; then
    echo "Senko config files already exist at ~/.config/senko."
else
    echo "Senko config files not found."
    echo "Creating Senko config files at ~/.config/senko."
    mkdir -p ~/.config/senko
    echo "Senko config files created."
fi

# find a compatible python3 interpreter (>= 3.10)
PYTHON=""
for candidate in python3 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$candidate" &> /dev/null; then
        if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -n "$PYTHON" ]; then
    "$PYTHON" main.py
else
    echo "No compatible Python found. Senko requires Python >= 3.10."
fi

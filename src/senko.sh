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

# checks for python3.11 interpreter on device 
if command -v python3.11 &> /dev/null; then 
    python3.11 main.py
else
    echo "python3.11 not found on device, please install first."
fi

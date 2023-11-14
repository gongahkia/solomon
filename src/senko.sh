#! /bin/bash

# checks for python3.11 interpreter on device 
if command -v python3.11 &> /dev/null; then 
    python3.11 main.py
else
    echo "python3.11 not found on device, please install first."
fi

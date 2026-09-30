#!/bin/bash
# Use pkexec to prompt for GUI password, fallback to sudo if run in terminal
if command -v pkexec &> /dev/null; then
    pkexec touch2key-setup
else
    sudo touch2key-setup
fi
echo "Press Enter to exit..."
read

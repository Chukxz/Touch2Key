#!/bin/bash
# Use pkexec to prompt for GUI password, fallback to sudo if run in terminal
if command -v pkexec &> /dev/null; then
    pkexec touch2key-uninstall
else
    sudo touch2key-uninstall
fi
echo "Press Enter to exit..."
read
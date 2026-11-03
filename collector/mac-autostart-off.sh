#!/bin/bash
PLIST="$HOME/Library/LaunchAgents/gg.custy.collector.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "Autostart removed and collector stopped."

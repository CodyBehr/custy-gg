#!/bin/bash
# Starts the collector in the background at every login on macOS, and starts it now.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3)"
PLIST="$HOME/Library/LaunchAgents/gg.custy.collector.plist"
[ -f "$DIR/config.json" ] || { echo "config.json is missing. Copy config.example.json to config.json and fill it in first."; exit 1; }
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>gg.custy.collector</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$DIR/custy_collector.py</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/dev/null</string>
  <key>StandardErrorPath</key><string>/dev/null</string>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Done. The collector runs in the background at login. Activity goes to $DIR/collector.log"

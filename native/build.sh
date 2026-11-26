#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
app_dir="$project_root/skill/prompt-aid/Prompt Aid.app"
mkdir -p "$app_dir/Contents/MacOS"
cat > "$app_dir/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>CFBundleName</key><string>Prompt Aid</string><key>CFBundleDisplayName</key><string>Prompt Aid</string><key>CFBundleIdentifier</key><string>dev.promptaid.review</string><key>CFBundleVersion</key><string>1</string><key>CFBundleShortVersionString</key><string>0.1.0</string><key>CFBundlePackageType</key><string>APPL</string><key>CFBundleExecutable</key><string>PromptAid</string><key>LSMinimumSystemVersion</key><string>13.0</string><key>NSHighResolutionCapable</key><true/></dict></plist>
PLIST
xcrun swiftc -target "$(uname -m)-apple-macos13.0" "$project_root/native/PromptAid.swift" -o "$app_dir/Contents/MacOS/PromptAid" -framework SwiftUI -framework AppKit
printf 'Built %s\n' "$app_dir"

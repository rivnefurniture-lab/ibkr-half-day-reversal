#!/bin/zsh
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"

rm -rf build "dist/Half-Day Reversal Connector" "dist/Half-Day Reversal Connector.app"
uv run --with pyinstaller pyinstaller --noconfirm --clean packaging/half_day_reversal.spec

app_path="$project_dir/dist/Half-Day Reversal Connector.app"
codesign --deep --force --sign - "$app_path"

staging_dir="$(mktemp -d)"
trap 'rm -rf "$staging_dir"' EXIT
cp -R "$app_path" "$staging_dir/"
ln -s /Applications "$staging_dir/Applications"

architecture="$(uname -m)"
output_path="$project_dir/dist/Half-Day-Reversal-macOS-${architecture}.dmg"
rm -f "$output_path"
hdiutil create -volname "Half-Day Reversal" -srcfolder "$staging_dir" -ov -format UDZO "$output_path"
echo "$output_path"

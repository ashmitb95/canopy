#!/bin/sh
# Builds the project page into _site: the page, the logo, and the webview preview it embeds as a live demo.
set -e
cd "$(dirname "$0")/.."
pnpm build:preview
rm -rf _site
mkdir -p _site
cp site/index.html media/canopy-icon.png media/canopy-mark.svg _site/
cp -R dist/preview _site/demo
rm -f _site/demo/screenshot-*.png
echo "Built _site. Preview it with: python3 -m http.server -d _site 8080"

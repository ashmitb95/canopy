#!/bin/sh
# Renders the README's images from the webview preview: the chat flow as a GIF, setup, and the lane view.
# Needs a headless Chromium (see scripts/screenshot.mjs) and ffmpeg. Run `pnpm build:preview` first.
set -e
cd "$(dirname "$0")/.."
CHROME=${CANOPY_CHROME:-$(ls -d "$HOME"/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell 2>/dev/null | tail -1)}
OUT=media/readme
FRAMES=$(mktemp -d)
mkdir -p "$OUT"
page() { echo "file://$PWD/dist/preview/index.html?theme=light&palette=paper&surface=$1&scenario=$2"; }
shot() { "$CHROME" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=2 --screenshot="$1" --window-size="$2" --virtual-time-budget="$3" "$4" >/dev/null 2>&1; }

# The chat: a frame every 200 ms of the scripted delegation, then the last frame held.
i=0
for t in $(seq 0 200 7400); do
  shot "$FRAMES/$(printf %03d $i).png" 1200,760 $((t + 150)) "$(page panel flow)"
  i=$((i + 1))
done
ffmpeg -loglevel error -y -framerate 5 -i "$FRAMES/%03d.png" -vf "tpad=stop_mode=clone:stop_duration=3,scale=1200:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4" "$OUT/chat.gif"

shot "$OUT/setup.png" 1200,760 3000 "$(page setup setup)"
shot "$OUT/lanes.png" 1200,700 3000 "$(page lanes lanes)"
rm -rf "$FRAMES"
ls -la "$OUT"

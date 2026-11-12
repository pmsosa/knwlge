#!/bin/sh
# Browser checks against a throw-away team-mode demo of made-up courses and people.
#
#   sh tools/e2e.sh            # the smoke test (tests/e2e/smoke.py)
#   sh tools/e2e.sh shots      # retake the user guide's screenshots into wiki/images
#
# It builds the image, writes a demo into a fresh folder under .e2e/, starts it on a free port, runs the browser
# job in a Playwright container, then removes the demo. Settings (environment variables):
#   E2E_IMAGE   image with Playwright for Python and Chromium (and Pillow for shots)
#               default: mcr.microsoft.com/playwright/python:v1.49.1-noble
#   E2E_RUN     command that starts that container, given docker-run options   default: docker run --rm
#   E2E_PORT    port for the demo                                               default: a free one
set -eu

cd "$(dirname "$0")/.."
ROOT=$(pwd)
MODE=${1:-smoke}
IMAGE=${E2E_IMAGE:-mcr.microsoft.com/playwright/python:v1.49.1-noble}
RUN=${E2E_RUN:-docker run --rm}
PORT=${E2E_PORT:-$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')}
STAMP=$(date +%Y%m%d-%H%M%S)-$$
WORK="$ROOT/.e2e/$STAMP"
NAME="knwlge-e2e-$STAMP"

mkdir -p "$WORK/data" "$WORK/out"
cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  # only ever this run's own folder under .e2e/
  case "$WORK" in "$ROOT/.e2e/"?*) rm -r -- "$WORK" ;; esac
}
trap cleanup EXIT

docker build -q -t knwlge-e2e . >/dev/null
docker run --rm -e KNWLGE_DATA=/demo -v "$WORK/data:/demo" knwlge-e2e python -m app.demo --team
docker run -d --name "$NAME" -e KNWLGE_DATA=/demo -e KNWLGE_MODE=team -e KNWLGE_NO_WORKER=1 \
  -v "$WORK/data:/demo" -p "127.0.0.1:$PORT:9180" knwlge-e2e >/dev/null

i=0
until curl -fs "http://127.0.0.1:$PORT/api/me" >/dev/null 2>&1; do
  i=$((i + 1)); [ "$i" -gt 60 ] && { echo "the demo didn't start"; docker logs "$NAME"; exit 1; }
  sleep 1
done
echo "demo running on port $PORT"

if [ "$MODE" = shots ]; then
  $RUN --network host -v "$ROOT/tools:/tools:ro" -v "$WORK/out:/out" "$IMAGE" \
    python /tools/screenshots.py "http://localhost:$PORT" /out
  cp "$WORK/out/"*.png "$ROOT/wiki/images/"
  echo "screenshots copied to wiki/images"
else
  $RUN --network host -v "$ROOT/tests/e2e:/e2e:ro" "$IMAGE" python /e2e/smoke.py "http://localhost:$PORT"
fi

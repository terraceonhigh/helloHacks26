#!/usr/bin/env bash
# Bring up PrairieLearn (dev mode) on 127.0.0.1:3100 and seed SCENARIO.md from scratch. Idempotent.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
NAME=fx-prairielearn
IMAGE=prairielearn/prairielearn:latest

# Fake credentials, generated once, never printed. PL dev login checks no password:
# FSTUDENT_PASSWORD exists only so every provider's secrets.env has the same shape.
if [ ! -f "$HERE/secrets.env" ]; then
  umask 077
  cat > "$HERE/secrets.env" <<EOT
FSTUDENT_UID=fstudent@example.invalid
FSTUDENT_NAME=Fake Student
FSTUDENT_EMAIL=fstudent@example.invalid
FSTUDENT_UIN=fstudent
FSTUDENT_PASSWORD=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')
FPROF_UID=fprof@example.invalid
FPROF_NAME=Fake Prof
FPROF_EMAIL=fprof@example.invalid
FPROF_UIN=fprof
FPROF_PASSWORD=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')
EOT
fi
# PL config: only our course (no example/test courses), random session-signing key.
if [ ! -f "$HERE/secrets.pl-config.json" ]; then
  umask 077
  printf '{ "courseDirs": ["/course"], "secretKey": "%s" }\n' "$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')" > "$HERE/secrets.pl-config.json"
fi
chmod 644 "$HERE/secrets.pl-config.json"   # the container's node user must read it; it's gitignored and local

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" \
  -p 127.0.0.1:3100:3000 \
  -e TZ=America/Vancouver \
  -v "$HERE/course:/course:ro" \
  -v "$HERE/secrets.pl-config.json:/PrairieLearn/config.json:ro" \
  "$IMAGE" >/dev/null

echo "waiting for PrairieLearn..."
for i in $(seq 90); do
  curl -sf http://127.0.0.1:3100/pl/webhooks/ping >/dev/null && break
  sleep 4
done
curl -sf http://127.0.0.1:3100/pl/webhooks/ping >/dev/null || { echo "PrairieLearn did not come up"; docker logs --tail 50 "$NAME"; exit 1; }

cd "$ROOT"
uv run python oracles/prairielearn/seed.py
echo "PrairieLearn up at http://127.0.0.1:3100 (container $NAME)"

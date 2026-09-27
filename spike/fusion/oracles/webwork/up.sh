#!/usr/bin/env bash
# Bring up WeBWorK on http://localhost:8081 and seed SCENARIO.md's WeBWorK part.
# Idempotent: builds the image once, generates secrets once, re-seeds every run.
#   FX_WEBWORK_REBUILD=1 ./up.sh   force an image rebuild
#   FX_WEBWORK_FRESH=1   ./up.sh   drop the volumes first (seed from scratch)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
IMAGE=fx-webwork-app:local
BUILD_DIR="${FX_WEBWORK_BUILD_DIR:-/var/tmp/fx-webwork-build}"

# 1. Secrets (random, fake, gitignored). Never printed.
if [ ! -f secrets.env ]; then
  rnd() { python3 -c 'import secrets; print(secrets.token_urlsafe(18))'; }
  umask 077
  cat > secrets.env <<S
FSTUDENT_PASSWORD=$(rnd)
FPROF_PASSWORD=$(rnd)
WW_ADMIN_PASSWORD=$(rnd)
WW_DB_PASSWORD=$(rnd)
WW_DB_ROOT_PASSWORD=$(rnd)
S
  echo "generated secrets.env"
fi
set -a; . ./secrets.env; set +a

# 2. Image. Upstream publishes no image, so build upstream's Dockerfile (slimmed).
if [ -n "${FX_WEBWORK_REBUILD:-}" ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  mkdir -p "$BUILD_DIR"
  for repo in webwork2 pg; do
    [ -d "$BUILD_DIR/$repo" ] || git clone -q --depth 1 --single-branch --branch main \
      "https://github.com/openwebwork/$repo.git" "$BUILD_DIR/$repo"
  done
  cp Dockerfile "$BUILD_DIR/Dockerfile"
  if [ -f /root/.ccr/ca-bundle.crt ]; then cp /root/.ccr/ca-bundle.crt "$BUILD_DIR/ca.crt"; else : > "$BUILD_DIR/ca.crt"; fi
  args=()
  if [ -n "${HTTPS_PROXY:-${https_proxy:-}}" ]; then
    args+=(--network host --build-arg "https_proxy=${HTTPS_PROXY:-$https_proxy}" --build-arg "no_proxy=localhost,127.0.0.1,registry.npmjs.org")
  fi
  docker build "${args[@]}" -t "$IMAGE" "$BUILD_DIR"
  docker image prune -f --filter label=fx.provider=webwork >/dev/null  # only our own dangling layers
fi

# 3. Containers.
if [ -n "${FX_WEBWORK_FRESH:-}" ]; then docker compose down -v; fi
docker compose up -d

# 4. Wait until WeBWorK answers (first start creates the admin course: ~1 min).
for i in $(seq 90); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8081/webwork2/ || true)
  [ "$code" = 200 ] && break
  sleep 5
done
[ "$code" = 200 ] || { echo "WeBWorK did not come up (last HTTP $code)"; docker logs --tail 50 fx-webwork-app; exit 1; }
echo "WeBWorK is up at http://localhost:8081/webwork2/"

# 5. Seed.
"$HERE/seed.sh"

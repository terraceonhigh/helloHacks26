#!/usr/bin/env bash
# Lifecycle script for the disposable Moodle oracle on humboldt (rootless
# podman, as terrace). Mirrors tests/live/webwork_selfhost/run.sh's shape:
# no compose tool on humboldt, so this is plain `podman run`, one function
# per subcommand. Run *on humboldt*, from ~/moodle (see this dir's README
# for how it got there and how to run it remotely over ssh).
#
# Images: docker.io/library/postgres:16 (DB) and
# docker.io/moodlehq/moodle-php-apache:8.2-bookworm - Moodle HQ's own CI
# image (PHP 8.2 + Apache + every extension Moodle needs), used as a base
# for a plain git checkout rather than Bitnami's Moodle image, which is
# deprecated. Moodle branch: MOODLE_405_STABLE (the current LTS as of this
# capture, 2026-09-28).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
MOODLE_DIR="${MOODLE_DIR:-$HOME/moodle}"
BIND_IP="${BIND_IP:-100.124.35.27}"
BIND_PORT="${BIND_PORT:-3004}"
NET=moodle-oracle-net
DB=moodle-oracle-db
WEB=moodle-oracle-web

usage() {
  cat <<EOF
Usage: $0 <command>
  up          first-time bring-up: network, secrets, git checkout, image
              pulls, DB + web containers, CLI install (idempotent)
  seed        copy setup_course.php in, run it, remove it again (idempotent)
  status      podman ps + a quick curl of the login page
  stop        podman stop (containers + data survive)
  start       podman start (after stop)
  rm          podman rm -f the two containers (volumes survive)
  wipe        rm containers + volumes + network (irreversible - everything
              in \$MOODLE_DIR/moodledata and the DB volume is gone)
EOF
}

need_secrets() {
  local f="$MOODLE_DIR/secrets.env"
  if [ ! -f "$f" ]; then
    umask 077
    {
      echo "MOODLE_DB_PASSWORD=$(openssl rand -base64 24 | tr -d '=+/')Aa1!"
      echo "MOODLE_ADMIN_USER=admin"
      echo "MOODLE_ADMIN_PASSWORD=$(openssl rand -base64 18 | tr -d '=+/')Aa1!"
      echo "MOODLE_STUDENT_USER=fakestudent"
      echo "MOODLE_STUDENT_PASSWORD=$(openssl rand -base64 18 | tr -d '=+/')Aa1!"
      echo "MOODLE_TEACHER_USER=fakeprof"
      echo "MOODLE_TEACHER_PASSWORD=$(openssl rand -base64 18 | tr -d '=+/')Aa1!"
    } > "$f"
    chmod 600 "$f"
    echo "wrote $f (chmod 600, values never printed)"
  fi
}

cmd_up() {
  mkdir -p "$MOODLE_DIR/moodledata"
  chmod 777 "$MOODLE_DIR/moodledata"  # world-writable to www-data inside the container; disposable data only
  need_secrets
  set -a; . "$MOODLE_DIR/secrets.env"; set +a

  if [ ! -d "$MOODLE_DIR/moodle/.git" ]; then
    GIT_TERMINAL_PROMPT=0 timeout 240 git clone --depth 1 --branch MOODLE_405_STABLE \
      https://github.com/moodle/moodle.git "$MOODLE_DIR/moodle"
  fi

  podman network create "$NET" 2>/dev/null || true
  timeout 240 podman pull docker.io/library/postgres:16
  timeout 240 podman pull docker.io/moodlehq/moodle-php-apache:8.2-bookworm

  if ! podman container exists "$DB"; then
    podman run -d --name "$DB" --network "$NET" \
      -e POSTGRES_USER=moodle -e POSTGRES_PASSWORD="$MOODLE_DB_PASSWORD" -e POSTGRES_DB=moodle \
      -v moodle-oracle-db-data:/var/lib/postgresql/data:Z \
      docker.io/library/postgres:16
  fi
  if ! podman container exists "$WEB"; then
    podman run -d --name "$WEB" --network "$NET" \
      -p "${BIND_IP}:${BIND_PORT}:80" \
      -v "$MOODLE_DIR/moodle:/var/www/html:Z" \
      -v "$MOODLE_DIR/moodledata:/var/www/moodledata:Z" \
      docker.io/moodlehq/moodle-php-apache:8.2-bookworm
  fi

  sleep 3
  if [ ! -f "$MOODLE_DIR/moodle/config.php" ]; then
    timeout 200 podman exec -e MOODLE_DB_PASSWORD -e MOODLE_ADMIN_PASSWORD "$WEB" \
      php admin/cli/install.php --non-interactive --agree-license \
      --wwwroot="http://${BIND_IP}:${BIND_PORT}" --dataroot="/var/www/moodledata" \
      --dbtype=pgsql --dbhost="$DB" --dbname=moodle --dbuser=moodle --dbpass="$MOODLE_DB_PASSWORD" \
      --fullname="Oracle Test Site" --shortname="OracleTest" \
      --adminuser="$MOODLE_ADMIN_USER" --adminpass="$MOODLE_ADMIN_PASSWORD" --adminemail="admin@example.invalid"
    # The CLI installer's config.php is written 0640 root:root, which Apache's
    # www-data can't read - fix once, here, rather than per-request.
    podman exec "$WEB" chmod 644 /var/www/html/config.php
  fi
  echo "up. http://${BIND_IP}:${BIND_PORT} (tailnet-only)"
}

cmd_seed() {
  set -a; . "$MOODLE_DIR/secrets.env"; set +a
  podman cp "$(dirname "${BASH_SOURCE[0]}")/setup_course.php" "$WEB:/var/www/html/setup_course.php"
  timeout 60 podman exec -e MOODLE_STUDENT_USER -e MOODLE_STUDENT_PASSWORD \
    -e MOODLE_TEACHER_USER -e MOODLE_TEACHER_PASSWORD "$WEB" php setup_course.php
  podman exec "$WEB" rm -f /var/www/html/setup_course.php  # never left web-servable
}

cmd_status() {
  podman ps --filter "name=moodle-oracle-" --format '{{.Names}} {{.Status}} {{.Ports}}'
  timeout 10 curl -sS --max-time 8 -o /dev/null -w 'login page: http=%{http_code}\n' \
    "http://${BIND_IP}:${BIND_PORT}/login/index.php" || true
}

case "${1:-}" in
  up) cmd_up ;;
  seed) cmd_seed ;;
  status) cmd_status ;;
  stop) podman stop "$WEB" "$DB" ;;
  start) podman start "$DB" "$WEB" ;;
  rm) podman rm -f "$WEB" "$DB" ;;
  wipe)
    podman rm -f "$WEB" "$DB" 2>/dev/null || true
    podman volume rm moodle-oracle-db-data 2>/dev/null || true
    podman network rm "$NET" 2>/dev/null || true
    echo "wiped containers/volume/network. $MOODLE_DIR (git checkout, moodledata, secrets.env) left on disk - rm -rf by hand if you want it gone too."
    ;;
  *) usage; exit 1 ;;
esac

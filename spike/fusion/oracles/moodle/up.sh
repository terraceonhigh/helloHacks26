#!/usr/bin/env bash
# Bring up the self-hosted Moodle (host port 8082) and seed SCENARIO.md into it.
# Idempotent: safe to re-run; it only creates what is missing and fixes drift.
#   ./up.sh            bring up + install (first time) + seed
#   ./up.sh --down     stop and remove containers (volumes kept)
#   ./up.sh --nuke     stop and remove containers AND volumes (fresh start next time)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
MOODLE_BRANCH=MOODLE_405_STABLE
IMG=moodlehq/moodle-php-apache:8.3

compose() { docker compose --env-file "$HERE/secrets.env" -f "$HERE/docker-compose.yml" "$@"; }

if [[ "${1:-}" == "--down" ]]; then compose down; exit 0; fi
if [[ "${1:-}" == "--nuke" ]]; then
  compose down -v || true
  docker volume rm fx-moodle-src 2>/dev/null || true
  exit 0
fi

# 1. Fake secrets (random, never printed). Kept if already there.
if [[ ! -f secrets.env ]]; then
  rnd() { python3 -c 'import secrets,string; a=string.ascii_letters+string.digits; print("Fx7!" + "".join(secrets.choice(a) for _ in range(20)))'; }
  umask 077
  cat > secrets.env <<EOF
MOODLE_DB_PASSWORD=$(rnd)
MOODLE_ADMIN_USER=admin
MOODLE_ADMIN_PASSWORD=$(rnd)
FSTUDENT_USERNAME=fstudent
FSTUDENT_PASSWORD=$(rnd)
FPROF_USERNAME=fprof
FPROF_PASSWORD=$(rnd)
EOF
  echo "wrote secrets.env (random fake passwords)"
fi
chmod 600 secrets.env

pull() { # docker hub anonymous pulls can 429: back off and retry
  for i in 1 2 3 4 5 6; do docker pull -q "$1" >/dev/null && return 0; echo "pull $1 failed, retry $i"; sleep $((i*10)); done; return 1; }
docker image inspect "$IMG" >/dev/null 2>&1 || pull "$IMG"
docker image inspect mirror.gcr.io/library/postgres:16-alpine >/dev/null 2>&1 || pull mirror.gcr.io/library/postgres:16-alpine

# 2. Moodle code in a docker volume (shallow clone, no .git) if not there yet.
docker volume inspect fx-moodle-src >/dev/null 2>&1 || docker volume create fx-moodle-src >/dev/null
if ! docker run --rm -v fx-moodle-src:/dst --entrypoint test "$IMG" -f /dst/version.php; then
  tmp="$(mktemp -d)"
  echo "cloning Moodle $MOODLE_BRANCH (shallow)..."
  git clone -q --depth 1 -b "$MOODLE_BRANCH" https://github.com/moodle/moodle "$tmp/src"
  rm -rf "$tmp/src/.git"
  tar -C "$tmp/src" -cf - . | docker run --rm -i -v fx-moodle-src:/dst --entrypoint tar "$IMG" -C /dst -xf -
  rm -rf "$tmp"
fi

# 3. config.php, written by us (not install.php) so settings are forced and reproducible.
set -a; source secrets.env; set +a
docker run --rm -i -v fx-moodle-src:/dst --entrypoint sh "$IMG" -c 'cat > /dst/config.php && chown www-data /dst/config.php' <<EOF
<?php  // Written by oracles/moodle/up.sh. Fake local test site.
unset(\$CFG);
global \$CFG;
\$CFG = new stdClass();
\$CFG->dbtype    = 'pgsql';
\$CFG->dblibrary = 'native';
\$CFG->dbhost    = 'fx-moodle-db';
\$CFG->dbname    = 'moodle';
\$CFG->dbuser    = 'moodle';
\$CFG->dbpass    = '${MOODLE_DB_PASSWORD}';
\$CFG->prefix    = 'mdl_';
\$CFG->dboptions = array('dbpersist' => 0, 'dbport' => 5432);
\$CFG->wwwroot   = 'http://localhost:8082';
\$CFG->dataroot  = '/var/www/moodledata';
\$CFG->admin     = 'admin';
\$CFG->directorypermissions = 02777;
\$CFG->noemailever = true;
\$CFG->lang = 'en';
require_once(__DIR__ . '/lib/setup.php');
EOF

# 4. Containers.
compose up -d
docker exec fx-moodle-app sh -c 'mkdir -p /var/www/moodledata && chown -R www-data:www-data /var/www/moodledata'

# 5. Install the database once (Moodle CLI).
if ! docker exec -u www-data fx-moodle-app php -r 'define("CLI_SCRIPT",1); require "/var/www/html/config.php"; exit($DB->get_manager()->table_exists("config") && !empty($CFG->version) ? 0 : 1);' >/dev/null 2>&1; then
  echo "installing Moodle database (takes a few minutes)..."
  docker exec -u www-data fx-moodle-app php /var/www/html/admin/cli/install_database.php \
    --agree-license --lang=en --fullname="Fusion Spike Moodle (fake)" --shortname=fxmoodle \
    --summary="Fake local Moodle for the fusion spike" \
    --adminuser="$MOODLE_ADMIN_USER" --adminpass="$MOODLE_ADMIN_PASSWORD" --adminemail=admin@example.invalid
fi

# Server timezone America/Vancouver (SCENARIO.md), forced for every user. Set as
# real site settings (in the DB, like an admin would), not config.php overrides.
docker exec -u www-data fx-moodle-app php /var/www/html/admin/cli/cfg.php --name=timezone --set=America/Vancouver
docker exec -u www-data fx-moodle-app php /var/www/html/admin/cli/cfg.php --name=forcetimezone --set=America/Vancouver

# 6. Wait for HTTP.
for i in $(seq 60); do curl -sf -o /dev/null http://localhost:8082/login/index.php && break; sleep 3; done
curl -sf -o /dev/null http://localhost:8082/login/index.php || { echo "Moodle not answering on :8082"; exit 1; }

# 7. Seed SCENARIO.md (idempotent PHP CLI script).
docker cp "$HERE/seed.php" fx-moodle-app:/tmp/fx_seed.php
set -a; source "$HERE/links.env"; set +a
docker exec -u www-data \
  -e FSTUDENT_PASSWORD="$FSTUDENT_PASSWORD" -e FPROF_PASSWORD="$FPROF_PASSWORD" \
  -e WW_BASE="$WW_BASE" -e PL_QUIZ1_URL="$PL_QUIZ1_URL" \
  fx-moodle-app php /tmp/fx_seed.php
echo "Moodle up at http://localhost:8082 and seeded."

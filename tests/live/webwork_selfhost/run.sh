#!/usr/bin/env bash
# Start the self-hosted WeBWorK oracle stack (rootless podman, plain podman
# translation of webwork2/docker-config/docker-compose.dist.yml).
# Secrets are read from ~/webwork/secrets.env and passed by name only.
set -euo pipefail
cd "$HOME/webwork"
set -a; . ./secrets.env
MYSQL_ROOT_PASSWORD=$WEBWORK_MYSQL_ROOT_PASSWORD MYSQL_USER=$WEBWORK_DB_USER MYSQL_PASSWORD=$WEBWORK_DB_PASSWORD
set +a
IP=100.124.35.27
podman network exists webwork-net || podman network create webwork-net
for v in webwork-mysql webwork-opl webwork-courses; do podman volume exists $v || podman volume create $v; done

podman container exists webwork-db || podman run -d --name webwork-db --network webwork-net --network-alias db \
  --restart always \
  -v webwork-mysql:/var/lib/mysql \
  -v "$HOME/webwork/webwork2/docker-config/db/mariadb.cnf:/etc/mysql/conf.d/mariadb.cnf:ro,Z" \
  -v "$HOME/webwork/webwork2/docker-config/db/mariadb.cnf:/etc/mysql/mariadb.cnf:ro,Z" \
  -e MYSQL_ROOT_PASSWORD -e MYSQL_DATABASE=webwork -e MYSQL_USER -e MYSQL_PASSWORD \
  docker.io/library/mariadb:11.8

podman container exists webwork-r || podman run -d --name webwork-r --network webwork-net --network-alias r \
  docker.io/ubcctlt/rserve

podman container exists webwork-app || podman run -d --name webwork-app --network webwork-net \
  --hostname webwork-oracle \
  -p $IP:3003:8080 \
  -v webwork-courses:/opt/webwork/courses \
  -v webwork-opl:/opt/webwork/libraries/webwork-open-problem-library \
  -e WEBWORK_DB_DRIVER=MariaDB -e WEBWORK_DB_HOST=db -e WEBWORK_DB_PORT=3306 -e WEBWORK_DB_NAME=webwork \
  -e WEBWORK_DB_USER -e WEBWORK_DB_PASSWORD \
  -e MIN_HTML_ERRORS=0 -e JSON_ERROR_LOG=0 \
  -e WEBWORK_ROOT_URL=http://$IP:3003 -e WEBWORK_TIMEZONE=America/Vancouver \
  --stop-signal SIGWINCH --stop-timeout 30 \
  localhost/webwork-app:2.21
podman ps --filter name=webwork- --format '{{.Names}} {{.Status}} {{.Ports}}'

#!/usr/bin/env bash
# Seed SCENARIO.md's WeBWorK part into the running fx-webwork-app container.
# Idempotent: safe to run again at any time. Called by up.sh.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP=fx-webwork-app
COURSE=math100_2026w1
set -a; . "$HERE/secrets.env"; set +a

WR=/opt/webwork/webwork2
CDIR=/opt/webwork/courses/$COURSE

# 1. Admin course password: replace upstream's default admin/admin with a random one.
docker exec -i -e ADMIN_PASSWORD="$WW_ADMIN_PASSWORD" "$APP" bash -c "cat > /tmp/fx-admin.pl" <<'PERL'
use WeBWorK::Utils qw(cryptPassword);
my $pw = $db->getPassword('admin') or die "no admin user\n";
$pw->password(cryptPassword($ENV{ADMIN_PASSWORD})); $db->putPassword($pw);
print "admin password rotated\n";
PERL
docker exec -e ADMIN_PASSWORD="$WW_ADMIN_PASSWORD" "$APP" sudo -E -u www-data $WR/bin/wwsh admin /tmp/fx-admin.pl | grep -q 'admin password rotated'

# 2. The course (bin/addcourse, WeBWorK's own CLI). Created once.
if ! docker exec "$APP" test -d "$CDIR"; then
  docker exec -w /opt/webwork/courses "$APP" sudo -E -u www-data $WR/bin/addcourse "$COURSE"
  echo "course $COURSE created"
else
  echo "course $COURSE already exists"
fi

# 3. Course config: timezone and 2FA off.
# Password courses have two-factor auth on by default; off here so the oracle
# can log in with a password only (at a real school, login is SSO and out of the adapter).
docker exec "$APP" bash -c "grep -q 'fx-spike v2' $CDIR/course.conf || cat >> $CDIR/course.conf <<'CONF'

# fx-spike v2: fake fusion-spike course settings
\$siteDefaults{timezone} = 'America/Vancouver';
\$twoFA{enabled} = 0;
# Plain-HTTP oracle: WeBWorK marks its session cookie Secure by default, and
# python-requests (unlike browsers on localhost) will not send it over http.
\$CookieSecure = 0;
CONF"

# 4. Templates: the trivial problem and the set definition files.
docker exec "$APP" mkdir -p /fx-seed
docker cp "$HERE/seed.pl" "$APP:/fx-seed/seed.pl"
for f in "$HERE"/templates/*; do docker cp "$f" "$APP:$CDIR/templates/$(basename "$f")"; done
docker exec "$APP" chown -R www-data:www-data "$CDIR/templates" /fx-seed

# 5. Users, passwords, sets (via bin/wwsh + WeBWorK's own .def importer).
out=$(docker exec -e FSTUDENT_PASSWORD="$FSTUDENT_PASSWORD" -e FPROF_PASSWORD="$FPROF_PASSWORD" \
  "$APP" sudo -E -u www-data $WR/bin/wwsh "$COURSE" /fx-seed/seed.pl)
echo "$out" | grep -E '^(user|sets|set import)' || true
if echo "$out" | grep -q '^errors' || ! echo "$out" | grep -q '^sets added: HW1 HW2 HW9 HW3$'; then
  echo "$out" >&2; echo "seed FAILED" >&2; exit 1
fi
echo "seed ok"

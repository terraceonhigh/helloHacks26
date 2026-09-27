# tests/live: opt-in live oracles (not collected by pytest)

Each `*_oracle.py` here runs against a real, self-hosted provider loaded with
FAKE data and prints PASS/FAIL per check (non-zero exit on any FAIL). INFO
lines record how the real system behaves where that matters to an adapter.
Nothing here runs under `pytest`: the filenames don't match `test_*.py`.

## `webwork_selfhost_oracle.py`

Logs in to a self-hosted WeBWorK 2.21 as the fake student of the fake course
`fake101`, through WeBWorK's normal login form (username/password, then the
default two-factor step), and records the ground truth for every set: name,
status, due instant with its timezone, deep link. If a WeBWorK adapter exists
in the checkout (`hub/webwork*.py`), it runs the adapter's `_run(req)` /
`fetch(req)` against the instance through a requests-backed shim of
Playwright's `APIRequestContext` and compares. Without one it prints the
ground truth and says "no adapter yet".

```bash
uv run python tests/live/webwork_selfhost_oracle.py                 # default http://100.124.35.27:3003/webwork2
uv run python tests/live/webwork_selfhost_oracle.py --save-fixtures # also rewrite tests/fixtures/webwork/*.html
```

Credentials: the fake course's two test accounts (`fakeprof`, `fakestudent`),
their TOTP secrets, and the DB/site-admin passwords live only in
`~/webwork/secrets.env` on humboldt (chmod 600). The oracle reads
`WW_STUDENT_USER`, `WW_STUDENT_PASSWORD` and `WW_STUDENT_OTP_SECRET` from the
environment if set, otherwise over ssh. It never prints them.

The fake course (all dates America/Vancouver; see
`webwork_selfhost/setup_course.sh`):

| set | open | due | case |
|---|---|---|---|
| FAKE_HW1_Past_Due | 2026-09-01 00:00 | 2026-09-20 23:59 | past due |
| FAKE_HW2_Due_Soon | 2026-09-15 00:00 | 2026-09-28 17:00 | due within 48 h of setup |
| FAKE_HW3_January_2027 | 2026-09-15 00:00 | 2027-01-15 23:59 | due after 2027-01-06 |
| FAKE_HW4_Not_Yet_Open | 2026-10-15 00:00 | 2026-10-22 23:59 | not open yet |
| FAKE_HW5_Far_Future | 2026-09-01 00:00 | 2099-12-31 23:59 | WeBWorK has no "no due date" |

Each set holds one OPL problem (`Library/Rochester/set0/prob1.pg`).

What real WeBWorK does that an adapter has to handle:
- The set list (`/webwork2/<course>/`) shows `Open. Due <date>` for open sets
  and `Will open on <open date>` for sets that aren't open yet. A past-due set
  shows only `Answers available for review.` with no date. Every set's own
  page says `This assignment will close on <date>`.
- Dates look like `January 15, 2027, 11:59:00 PM PST`: a `%Z` abbreviation,
  no numeric offset.
- WeBWorK's Perl `DateTime::TimeZone` (2.65, bundling tzdata 2025b) predates
  BC's permanent-DST change, so it still shows PST (UTC-8) for Vancouver
  after 2026-11-01. tzdata 2026c (the container's own `tzdata` package, and
  this Mac) says UTC-7 "MST". The server's instant is the one the student is
  held to, so an adapter must honour the abbreviation on the page and not
  re-derive the offset from `America/Vancouver`.
- Password courses have two-factor auth on by default
  (`$twoFA{enabled} = 1`). A first login shows a QR code, and later logins ask
  for a TOTP code. The fake users' secrets are pre-provisioned so the oracle
  can compute codes.

### Start / stop (humboldt, rootless podman)

There's no official prebuilt image. The image is built from the official
`webwork2` repo's single-stage `Dockerfile`, and `docker-compose.dist.yml` is
translated to plain `podman run` in `webwork_selfhost/run.sh`, because
humboldt has no compose tool. It runs three containers on network `webwork-net`:
`webwork-db` (mariadb:11.8), `webwork-r` (ubcctlt/rserve) and `webwork-app`,
which listens on `100.124.35.27:3003` only.

```bash
# first time, on humboldt
mkdir -p ~/webwork/logs && cd ~/webwork
git clone --depth 1 https://github.com/openwebwork/webwork2.git
podman pull docker.io/alpine/git:latest    # pre-pull the Dockerfile's short-named bases,
podman pull docker.io/library/ubuntu:26.04 # else podman build stops at a short-name prompt
(cd webwork2 && podman build --tag localhost/webwork-app:2.21 -f Dockerfile \
   --build-arg ADDITIONAL_BASE_IMAGE_PACKAGES= \
   --build-arg WEBWORK2_GIT_URL=https://github.com/openwebwork/webwork2.git --build-arg WEBWORK2_BRANCH=main \
   --build-arg PG_GIT_URL=https://github.com/openwebwork/pg.git --build-arg PG_BRANCH=main .)
# write ~/webwork/secrets.env (chmod 600) with WEBWORK_DB_USER, WEBWORK_DB_PASSWORD,
#   WEBWORK_MYSQL_ROOT_PASSWORD, WW_SITE_ADMIN_PASSWORD, WW_INSTRUCTOR_USER/_PASSWORD/_OTP_SECRET,
#   WW_STUDENT_USER/_PASSWORD/_OTP_SECRET
cp <repo>/tests/live/webwork_selfhost/{run.sh,setup_course.sh} ~/webwork/
~/webwork/run.sh      # first start clones the OPL (~2.5 GB volume) and loads its tables
# once `podman logs webwork-app` says "Web application available":
set -a; . ~/webwork/secrets.env; set +a
podman exec -i -u www-data -e WW_SITE_ADMIN_PASSWORD -e WW_INSTRUCTOR_USER -e WW_INSTRUCTOR_PASSWORD \
  -e WW_STUDENT_USER -e WW_STUDENT_PASSWORD -e WW_INSTRUCTOR_OTP_SECRET -e WW_STUDENT_OTP_SECRET \
  webwork-app bash -s < ~/webwork/setup_course.sh

podman stop webwork-app webwork-r webwork-db       # stop
podman start webwork-db webwork-r webwork-app      # start again (state is in the webwork-* volumes)
podman rm -f webwork-app webwork-r webwork-db      # remove the containers (volumes survive)
podman volume rm webwork-mysql webwork-opl webwork-courses && podman network rm webwork-net   # wipe everything
```

`setup_course.sh` uses WeBWorK's own tools: `bin/addcourse
--templates-from=modelCourse --users=<classlist>` and
`WeBWorK::File::SetDef::importSetsFromDef`, which is the code behind the Sets
Manager's Import. It also replaces the entrypoint's default `admin`/`admin`
site-admin password, runs `bin/upgrade_admin_db.pl` (the entrypoint skips it
on a fresh DB, which leaves `lti_course_map` missing), and adds
`$CookieSecure = 0` to `fake101/course.conf`, because the default Secure
cookie is never sent back over this plain-HTTP tailnet URL and login loops.
Keep everything in the course fake.

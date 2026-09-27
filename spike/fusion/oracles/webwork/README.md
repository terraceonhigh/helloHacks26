# WeBWorK oracle server

A real WeBWorK 2.21 (openwebwork/webwork2 `main` + pg `main`) with MariaDB 11.8,
seeded with the WeBWorK part of SCENARIO.md. Fake data and fake credentials only.

| what | value |
|---|---|
| URL | http://localhost:8081/webwork2/ (bound to 127.0.0.1 only) |
| course | `math100_2026w1` → http://localhost:8081/webwork2/math100_2026w1 |
| users | `fstudent` (student, "Fake Student"), `fprof` (professor, permission 10) |
| sets | HW1, HW2, HW9, HW3, one trivial local problem each (`templates/fx_trivial.pg`) |
| containers | `fx-webwork-app`, `fx-webwork-db`; network `fx-webwork-net`; volumes `fx-webwork-mysql`, `fx-webwork-courses` |
| image | `fx-webwork-app:local`, built locally (~2 GB) |
| secrets | `secrets.env` (gitignored, mode 600): `FSTUDENT_PASSWORD`, `FPROF_PASSWORD`, `WW_ADMIN_PASSWORD`, `WW_DB_PASSWORD`, `WW_DB_ROOT_PASSWORD` |

**Deep links for other providers** (SCENARIO's `<WW:HWn>`): `http://localhost:8081/webwork2/math100_2026w1/HWn`,
for example `http://localhost:8081/webwork2/math100_2026w1/HW2`. That is the set's own page, the same URL
the adapter emits as `url`. WeBWorK's own links add `?effectiveUser=fstudent`, and a trailing `/`
also works. Both are per-viewer noise, so fusion should normalise them away.

## Up / seed / login / down

```bash
oracles/webwork/up.sh                       # idempotent: build image if missing, secrets if missing, up, wait, seed
FX_WEBWORK_FRESH=1 oracles/webwork/up.sh    # drop the volumes first: everything from scratch (~15 s once the image exists)
FX_WEBWORK_REBUILD=1 oracles/webwork/up.sh  # force an image rebuild (~10 min)
oracles/webwork/seed.sh                     # re-seed only
uv run python oracles/webwork/login.py      # smoke-test the student login
uv run python oracles/webwork_oracle.py [--save-fixtures]
cd oracles/webwork && set -a && . ./secrets.env && set +a && docker compose down     # stop (add -v to drop data)
```

`login.login(base, secrets)` takes the server root (`http://localhost:8081`) or the course URL
and returns a `requests.Session` logged in as fstudent. `adapters.webwork.fetch(session, base)`
accepts the same two forms. From the root it reads every course on the site index that the
session is logged in to.

## How the server is built (and what was cut)

- **No published upstream image.** `openwebwork/webwork2` isn't on Docker Hub or GHCR. Upstream's
  docs build `Dockerfile` from the repo, and `Dockerfile` here is a slimmed copy of it. up.sh clones
  webwork2 and pg (`--depth 1`) into `/var/tmp/fx-webwork-build`.
- ponytail: **no TeX Live** (~2 GB) and no dvipng/dvisvgm/pdf2svg/imagemagick, so hardcopy (PDF)
  and TeX-rendered images don't work. `libpaper2` is installed explicitly, because upstream's
  entrypoint `dpkg-reconfigure`s it under `set -e` and otherwise crash-loops.
- ponytail: **no Open Problem Library.** An empty `OpenProblemLibrary/` dir plus a stub
  `htdocs/DATA/tagging-taxonomy.json` stop the entrypoint from cloning the OPL (~850 MB) and
  running OPL-update.
- The build host's egress is an HTTPS-only, TLS-re-terminating proxy, so the build uses
  `--network host`, switches apt to https mirrors, and trusts the proxy CA.
- The admin course's default `admin/admin` password is rotated to `WW_ADMIN_PASSWORD` on every seed.

## How seeding works (seed.sh, idempotent)

1. `bin/addcourse math100_2026w1` (WeBWorK's CLI), once.
2. Appends to the course's `course.conf`:
   - `$siteDefaults{timezone} = 'America/Vancouver'`
   - `$twoFA{enabled} = 0`. **Two-factor auth is on by default for password courses.** It's off
     here so the oracle can log in with a password only. At a school, login is SSO and outside the adapter.
   - `$CookieSecure = 0`. See the behaviours below.
3. Copies `templates/*` (the `.pg` problem and `setHWn.def` files) into the course templates.
4. `bin/wwsh math100_2026w1 seed.pl` upserts fstudent and fprof (crypted passwords from
   `secrets.env`, never printed), deletes the four scenario sets, and re-imports them through
   WeBWorK's own `.def` importer (`WeBWorK::File::SetDef::importSetsFromDef`), assigned to all users.
   The `.def` dates are wall-clock times with no zone, so WeBWorK interprets them in the course zone
   with its own tz database, just as an instructor typing them in would.

## Real-server behaviours an adapter must handle

1. **No student JSON.** A student reads HTML only: the course page (set list) and each set's page.
2. **Which date the student can see depends on the set's state** (verified on 2.21):

   | state (`li[data-set-status]`) | set list line | set page status line |
   |---|---|---|
   | `open` | `Open. Due <date>.` | `Set closes on <date>.` |
   | `not-open` | `Will open on <date>.` | `Set opens on <date>.` |
   | `past-due` | `Answers available for review[ on <answer date>].` | `Set is closed.` |

   For past-due and not-yet-open sets, the **only** student-visible due date is the set header
   ("Set Info", `#info-panel-right`). WeBWorK's default header prints `This assignment will close
   on <date>.` An instructor can replace that header. The adapter then returns `due=None` plus a
   Snapshot note and never guesses. The open date disappears once a set is open, so `opens` is set
   only for not-open sets. With reduced scoring on, the list's "Open. Due X" is the reduced-scoring
   start, which is why the adapter prefers the set page's "Set closes on".
3. **Dates** look like `September 29, 2026, 11:59:00 PM PDT` (`datetime_format_long`, `en`
   locale; older releases print `... 2026 at 11:59pm PDT`). The zone is an **abbreviation** chosen
   by WeBWorK's Perl tz database. Map it to a fixed offset. Never re-derive the offset from
   `America/Vancouver`.
4. **Two tz databases disagree after 2026-11-01.** WeBWorK stored HW9's due (entered as
   2027-01-15 23:59) as epoch 1800086340 = 2027-01-16T07:59Z and prints it as `11:59:00 PM PST`
   (UTC-8). The containers' OS tzdata (Ubuntu 26.04 / MariaDB 11.8) renders the same epoch as
   2027-01-16 00:59, because it has BC on UTC-7 from 2026-11-01. The instant the student is held to
   is WeBWorK's. The oracle prints this as an INFO line.
5. **Session cookie**: `WeBWorKCourseSession.<course>`, one per course, path `/webwork2`, 30-minute
   idle expiry. It's marked `Secure` by default. Browsers still send it to `http://localhost`, but
   python-requests won't, so the fake course sets `$CookieSecure = 0`. Behind real HTTPS this doesn't matter.
6. A failed login re-renders `form#login_form` with HTTP 200. Detect login pages by that id.
7. Links in the HTML carry `?effectiveUser=<user>`. The adapter strips the query from `url`.
8. Set ids with `_` display with spaces (`format_set_name_display`). The adapter's title is the
   displayed name, and `source_id` is `<course>/<set id from the href>`.
9. Gateway/quiz sets show `data-set-type="test"`, which the adapter maps to kind `quiz`. Regular
   sets map to `homework`. (SCENARIO has only regular sets. The gateway path isn't live-verified.)
10. `done` comes from the set page's problem table (every problem's Status 100%). It's `None` when
    there's no table (not-open sets).
11. WeBWorK has no term field. `term_hint` is `None`, and the term lives only in the course id
    (`math100_2026w1`), which is the CourseObservation `label`. The printed course title is
    `math100 2026w1`.

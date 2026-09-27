"""Seed SCENARIO.md's PrairieLearn part into the fx-prairielearn container. Idempotent.

Course content (course CPSC 121, instance 2026W1, quiz1/ps3/quiz2/lab4 with
their credit windows, timezone America/Vancouver) lives on disk in ./course and
is synced by PrairieLearn's own "Load from disk". Users are created by logging
them in once (that's how PL creates users). Enrolment and staff permission are
then written straight into PL's bundled Postgres.

# ponytail: enrolment/permissions via SQL rather than the instructor UI's
# invite flow (which leaves a pending invite the student must accept). Upgrade
# path: drive /pl/course_instance/<id>/instructor/instance_admin/students as
# fprof, then accept as fstudent.
"""
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from oracles.prairielearn.login import dev_login, read_secrets  # noqa: E402

CONTAINER = "fx-prairielearn"
BASE = "http://127.0.0.1:3100"


def psql(sql: str) -> str:
    r = subprocess.run(["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", "postgres",
                        "-v", "ON_ERROR_STOP=1", "-At", "-F", "\t"],
                       input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
    return r.stdout.strip()


def load_from_disk():
    s = requests.Session()   # no disable cookie: dev mode auto-authenticates as the dev admin
    r = s.get(f"{BASE}/pl/loadFromDisk", timeout=60, allow_redirects=False)
    if r.status_code not in (302, 303):
        raise RuntimeError(f"loadFromDisk: HTTP {r.status_code}")
    job = r.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    for _ in range(60):
        st = psql(f"select status from job_sequences where id = {int(job)}")
        if st and st != "Running":
            break
        time.sleep(2)
    if st != "Success":
        raise RuntimeError(f"loadFromDisk job {job} ended {st!r}")
    errs = psql("select tid || ': ' || sync_errors from assessments where sync_errors is not null "
                "union all select short_name || ': ' || sync_errors from course_instances where sync_errors is not null")
    if errs:
        raise RuntimeError(f"course sync errors:\n{errs}")


def main():
    sec = read_secrets()
    load_from_disk()
    ci = psql("select ci.id from course_instances ci join courses c on c.id = ci.course_id "
              "where c.short_name = 'CPSC 121' and ci.short_name = '2026W1' and ci.deleted_at is null")
    if not ci:
        raise RuntimeError("course instance CPSC 121 / 2026W1 not synced")
    ci = int(ci)
    n = psql(f"select count(*) from assessments where course_instance_id = {ci} and deleted_at is null")
    if n != "4":
        raise RuntimeError(f"expected 4 assessments, found {n}")

    # Create the users the way PL does: by logging them in once.
    dev_login(BASE, sec["FSTUDENT_UID"], sec["FSTUDENT_NAME"], sec.get("FSTUDENT_UIN"), sec.get("FSTUDENT_EMAIL"))
    dev_login(BASE, sec["FPROF_UID"], sec["FPROF_NAME"], sec.get("FPROF_UIN"), sec.get("FPROF_EMAIL"))

    def q(v):
        return "'" + v.replace("'", "''") + "'"

    psql(f"""
    begin;
    insert into enrollments (user_id, course_instance_id, status, first_joined_at)
      select u.id, {ci}, 'joined', now() from users u where u.uid = {q(sec['FSTUDENT_UID'])}
      and not exists (select 1 from enrollments e where e.user_id = u.id and e.course_instance_id = {ci});
    update enrollments set status = 'joined', first_joined_at = coalesce(first_joined_at, now())
      where course_instance_id = {ci} and user_id = (select id from users where uid = {q(sec['FSTUDENT_UID'])});
    insert into course_permissions (user_id, course_id, course_role)
      select u.id, ci.course_id, 'Owner' from users u, course_instances ci
      where u.uid = {q(sec['FPROF_UID'])} and ci.id = {ci}
      and not exists (select 1 from course_permissions p where p.user_id = u.id and p.course_id = ci.course_id);
    insert into course_instance_permissions (course_instance_id, course_instance_role, course_permission_id)
      select {ci}, 'Student Data Editor', p.id from course_permissions p join users u on u.id = p.user_id
      where u.uid = {q(sec['FPROF_UID'])}
      and not exists (select 1 from course_instance_permissions x where x.course_permission_id = p.id and x.course_instance_id = {ci});
    commit;
    """)
    print(f"seeded: course instance {ci}, 4 assessments, fstudent enrolled, fprof Owner")


if __name__ == "__main__":
    main()

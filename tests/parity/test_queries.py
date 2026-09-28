"""Parity for lauds.store's queries against tests/oracle/queries/*.json.

Each golden's "seed" (in `extra.seed`) names the main test(s) it replays
(tests/test_db.py, tests/test_db_schedule.py, tests/test_db_oracle_pr33.py,
tests/test_key_dates_oracle.py) - `SEEDS` below rebuilds the exact same
`lauds.store.save()` calls, in the same order, from those tests' own
constants. The golden's "result" is `{"now_a": {...}, "now_b": {...}}`, one
full dump of every query (+status_of) at each of two fixed clocks - not one
of tests/parity/superset.py's own named QUERY_ROWS shapes, so it's compared
by plain equality (`_generic_result`): `new` must be built in exactly that
shape, with lauds' extra trailing `id` column trimmed off item rows to match
main's column count (BRIEF.md: extra columns are allowed, but only where the
comparator itself does the trimming, i.e. inside a named-query golden)."""
import json
from datetime import date, datetime, time, timezone

import pytest

from lauds import store
from lauds.models import Course, Item, Meeting, Textbook, status_of
from tests.parity.superset import assert_superset, golden_paths, load_golden

UTC = timezone.utc

# --- shared constants, lifted verbatim from main's tests -------------------

COURSE = Course(code="CPSC 121", section="", term="2026W1", title="Models of Computation", grade=88.5)
OTHER_COURSE = Course(code="ENGL 112", section="", term="2026W1", title="Strategies for University Writing")
QUIZ = Item(course="CPSC 121", category="deadline", kind="quiz", title="Quiz 2",
            due=datetime(2026, 9, 30, 6, 59, tzinfo=UTC), url="https://x/q/1", source="canvas")
BOOK = Textbook(course="CPSC 121", title="Discrete Math", isbn="123", required=True, price=80.0, url="https://x/b/1")
LECTURE = Meeting(course="CPSC 121", kind="lecture", days=["MO", "WE", "FR"],
                   start_time=time(10, 0), end_time=time(11, 0), location="ICCS 101",
                   term_start=date(2026, 9, 8), term_end=date(2026, 12, 5), source="workday")


def _seed_basic_save_and_upcoming(conn):
    store.save(conn, [COURSE], [QUIZ], [BOOK])


def _seed_category_filter(conn):
    reading = Item(course="CPSC 121", category="material", kind="reading", title="Ch. 3",
                    due=datetime(2026, 9, 29, tzinfo=UTC), url="https://x/r/1", source="canvas")
    store.save(conn, [COURSE], [QUIZ, reading])


def _seed_undated_vs_upcoming(conn):
    announcement = Item(course="CPSC 121", category="task", kind="announcement", title="Welcome!",
                         due=None, url="https://x/a/1", source="canvas")
    store.save(conn, [COURSE], [QUIZ, announcement])


def _seed_undated_most_recent_first(conn):
    first = Item(course="CPSC 121", category="task", kind="announcement", title="First",
                 due=None, url="https://x/a/1", source="canvas")
    second = Item(course="CPSC 121", category="task", kind="announcement", title="Second",
                  due=None, url="https://x/a/2", source="canvas")
    store.save(conn, [COURSE], [first])
    store.save(conn, [COURSE], [second])


def _seed_done_clobbered_by_a_later_unknown_write(conn):
    # BRIEF major finding + DIVERGENCES.md: main's own upsert (hub/db.py)
    # unconditionally does `done=excluded.done`, so a second, less-informed
    # write (e.g. Canvas's .ics feed re-saving the same (source, url) with
    # no completion signal at all) erases a real done=True. lauds' store
    # now uses COALESCE(excluded.done, done) instead - a documented,
    # evidenced divergence from this exact golden's "done" field.
    done_then_unknown = Item(course="CPSC 121", category="task", kind="quiz", title="Quiz 2",
                              due=datetime(2026, 9, 30, 6, 59, tzinfo=UTC), url="https://x/q/1",
                              source="canvas", done=True)
    done_then_unknown_reupsert = Item(**{**done_then_unknown.__dict__, "done": None})
    store.save(conn, [COURSE], [done_then_unknown])
    store.save(conn, [COURSE], [done_then_unknown_reupsert])


def _seed_courses_and_by_course_grouping(conn):
    essay = Item(course="ENGL 112", category="task", kind="assignment", title="Essay 1",
                 due=datetime(2026, 10, 1, tzinfo=UTC), url="https://x/e/1", source="canvas")
    store.save(conn, [COURSE, OTHER_COURSE], [QUIZ, essay])


def _seed_textbooks_ordering(conn):
    optional_book = Textbook(course="CPSC 121", title="Companion Reader", isbn="999",
                              required=False, price=None, url="")
    store.save(conn, [COURSE], [], [optional_book, BOOK])


def _seed_canvas_long_code_joins_workday_short_code(conn):
    workday_course = Course(code="CPSC 121", section="", term="2026W1", title="Models of Computation")
    canvas_item = Item(course="CPSC 121 101 2026W1", category="task", kind="assignment", title="PS3",
                        due=datetime(2026, 9, 28, tzinfo=UTC), url="https://canvas/1", source="canvas")
    store.save(conn, [workday_course], [canvas_item])


def _seed_orphan_item_before_course_known(conn):
    orphan = Item(course="PHIL 100", category="task", kind="assignment", title="Essay",
                  due=datetime(2026, 9, 28, tzinfo=UTC), url="https://x/orphan", source="canvas")
    store.save(conn, [], [orphan])


_PR33_DUE = datetime(2026, 10, 2, 6, 59, tzinfo=UTC)
_PR33_QUIZ = Item(course="CPSC 121 101 2026W1", category="deadline", kind="quiz", title="Quiz 3",
                   due=_PR33_DUE, url="https://canvas.example/quiz/3", source="canvas")


def _seed_orphan_item_before_course_arrives(conn):
    store.save(conn, [], [_PR33_QUIZ])  # course not known yet


def _seed_orphan_item_after_course_arrives(conn):
    store.save(conn, [], [_PR33_QUIZ])
    store.save(conn, [Course(code="CPSC 121 101 2026W1", section="101", term="2026W1",
                             title="Models of Computation")], [_PR33_QUIZ])


def _seed_pr33_term_spellings_join_one_course_row(conn):
    store.save(conn, [Course(code="CPSC 121", section="", term="", title="CPSC 121")])
    store.save(conn, [Course(code="CPSC 121 101 2026W1", section="101", term="2026 Winter Term 1",
                             title="Models of Computation", grade=84.0)])
    store.save(conn, [Course(code="CPSC 121", section="101", term="2026W1", title="Models of Computation")])


def _seed_pr33_lab_shell_grade_none_does_not_erase_lecture_grade(conn):
    lecture = Course(code="CPSC 121 101 2026W1", section="101", term="2026W1",
                     title="Models of Computation", grade=84.0)
    lab = Course(code="CPSC 121 L1A 2026W1", section="L1A", term="2026W1",
                 title="Models of Computation (Lab)", grade=None)
    store.save(conn, [lecture, lab])


def _seed_pr33_lecture_then_lab_shorter_title_wins(conn):
    lecture = Course(code="CPSC 121 101 2026W1", section="101", term="2026W1", title="Models of Computation")
    lab = Course(code="CPSC 121 L1A 2026W1", section="L1A", term="2026W1", title="Models of Computation (Lab)")
    store.save(conn, [lecture, lab])


def _seed_pr33_lab_then_lecture_shorter_title_still_wins(conn):
    lecture = Course(code="CPSC 121 101 2026W1", section="101", term="2026W1", title="Models of Computation")
    lab = Course(code="CPSC 121 L1A 2026W1", section="L1A", term="2026W1", title="Models of Computation (Lab)")
    store.save(conn, [lab, lecture])  # lab first - same result either way


def _seed_pr33_none_term_does_not_crash(conn):
    store.save(conn, [Course(code="CPSC 121", section="", term=None, title="CPSC 121")])


def _seed_schedule_basic(conn):
    store.save(conn, [COURSE], meetings=[LECTURE])


def _seed_schedule_idempotent_update(conn):
    store.save(conn, [COURSE], meetings=[LECTURE])
    moved = Meeting(**{**LECTURE.__dict__, "location": "ICCS 200"})
    store.save(conn, [COURSE], meetings=[moved])


def _seed_schedule_second_distinct_time_slot_kept_separately(conn):
    other_slot = Meeting(**{**LECTURE.__dict__, "days": ["FR"], "start_time": time(9, 0), "end_time": time(10, 0)})
    store.save(conn, [COURSE], meetings=[LECTURE, other_slot])


def _seed_schedule_meeting_with_unmatched_course_skipped(conn):
    store.save(conn, [], meetings=[LECTURE])


def _seed_schedule_canvas_and_workday_join_same_course(conn):
    long_code_course = Course(code="CPSC 121 101 2026W1", section="101", term="2026W1", title="Models of Computation")
    store.save(conn, [long_code_course], meetings=[LECTURE])


_KEY_DATES_FIRST = Item(
    course="UBCV", category="deadline", kind="payment", title="Tuition: 1st instalment due (Winter Session)",
    due=datetime(2026, 9, 9, 23, 59, tzinfo=timezone(__import__("datetime").timedelta(hours=-7))),
    url="https://vancouver.calendar.ubc.ca/fees/policies-fees#1st-instalment-2026w1", source="ubc_key_dates",
    done=True,  # already elapsed at harvest time (fetch()'s own job, not db's) - never "overdue" (PR #37)
)
_KEY_DATES_SECOND = Item(
    course="UBCV", category="deadline", kind="payment", title="Tuition: 2nd instalment due (Winter Session)",
    due=datetime(2027, 1, 6, 23, 59, tzinfo=timezone(__import__("datetime").timedelta(hours=-7))),
    url="https://vancouver.calendar.ubc.ca/fees/policies-fees#2nd-instalment-2026w1", source="ubc_key_dates",
    done=None,
)


def _seed_key_dates_ubcv_round_trip_after_first_instalment(conn):
    store.save(conn, [Course(code="UBCV", section="", term="2026W1", title="UBC Vancouver")],
               [_KEY_DATES_FIRST, _KEY_DATES_SECOND])


SEEDS = {name[len("_seed_"):]: fn for name, fn in list(globals().items()) if name.startswith("_seed_")}

GOLDENS = golden_paths("queries")
MISSING = [p.stem for p in GOLDENS if p.stem not in SEEDS]
assert not MISSING, f"tests/parity/test_queries.py has no seed for: {MISSING}"


# --- replaying every query at both fixed clocks ----------------------------

def _item_row_trimmed(row):
    return list(row[:8])  # drop lauds' trailing `id` column - see module docstring


def _dump(conn, now: datetime) -> dict:
    upcoming = store.upcoming(conn)
    by_cat = {cat: [_item_row_trimmed(r) for r in store.upcoming(conn, cat)]
              for cat in ("task", "deadline", "material")}
    by_course = {code: [_item_row_trimmed(r) for r in rows] for code, rows in store.by_course(conn).items()}

    def status(row):
        item = Item(course=row[0], category=row[1], kind=row[2], title=row[3],
                    due=None if row[4] is None else datetime.fromisoformat(row[4]), url=row[5],
                    source=row[7], done=None if row[6] is None else bool(row[6]))
        return status_of(item, now=now)

    return {
        "now": now.isoformat(),
        "upcoming": [_item_row_trimmed(r) for r in upcoming],
        "upcoming_by_category": by_cat,
        "undated": [_item_row_trimmed(r) for r in store.undated(conn)],
        "courses": [list(r) for r in store.courses(conn)],
        "by_course": by_course,
        "textbooks": [list(r) for r in store.textbooks(conn)],
        "schedule": [list(r) for r in store.schedule(conn)],
        "status_of_upcoming": [status(r) for r in upcoming],
    }


@pytest.mark.parametrize("golden", GOLDENS, ids=lambda p: p.stem)
def test_queries_parity(golden):
    g = load_golden(golden)
    conn = store.connect(":memory:")
    SEEDS[golden.stem](conn)
    now_a, now_b = (datetime.fromisoformat(s) for s in g["now"])
    new = {"now_a": _dump(conn, now_a), "now_b": _dump(conn, now_b)}
    assert_superset(golden, new)

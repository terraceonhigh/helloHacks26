"""Demo frontend: what's due next, across every connected provider."""
from datetime import datetime, timedelta, timezone

import streamlit as st

from hub import bookstore, canvas, db, export_ics, key_dates, prairielearn
from hub.logic import sort_items
from hub.models import Course, Item, category_for, classify_urgency, status_of

st.set_page_config(page_title="UBC Hub")
st.title("UBC Hub")
st.caption("Gotham for students: every provider, one pane of glass.")


def sample_conn():
    """In-memory DB with made-up items, so the demo runs without a Canvas login."""
    # ponytail: rebuilt every rerun (it's tiny). Swap for fixtures/ once Vihaan's land on main.
    now = datetime.now(timezone.utc)
    rows = [("CPSC 121", "Problem Set 3", "assignment", 2), ("CPSC 121", "Quiz 2", "quiz", 4),
            ("MATH 100", "Midterm 1", "exam", 9), ("ENGL 110", "Read ch. 4", "reading", 1),
            ("MATH 100", "WeBWorK 3", "assignment", -1)]
    courses = [Course(code=c, section="101", term="2026W1", title=c) for c in {r[0] for r in rows}]
    items = [Item(course=c, category=category_for(k), kind=k, title=t, due=now + timedelta(days=d),
                  url=f"https://example.invalid/{n}", source="sample") for n, (c, t, k, d) in enumerate(rows)]
    conn = db.connect(":memory:")
    db.save(conn, courses, items)
    return conn


@st.cache_data(ttl=86400)  # design.md: Bookstore data is cached per term - textbook lists barely change
def _bookstore_lookup(course_code, term):
    return bookstore.fetch(course_code, term)


with st.sidebar:
    demo = st.toggle("Sample data", value=True, help="Off = your own Canvas data from this laptop's hub.db")
    if not demo:
        col1, col2 = st.columns(2)
        if col1.button("Connect Canvas", help="Opens a browser window: sign in with CWL + Duo yourself"):
            with st.spinner("Waiting for you to sign in to Canvas…"):
                db.save(db.connect(), *canvas.fetch())
        if col2.button("Connect PrairieLearn", help="Opens a browser window: sign in with CWL + Duo yourself"):
            with st.spinner("Waiting for you to sign in to PrairieLearn…"):
                db.save(db.connect(), *prairielearn.fetch())
    n = st.slider("Show next", 5, 50, 10)
    hide_overdue = st.toggle("Hide overdue", value=False)

conn = sample_conn() if demo else db.connect()
db.save(conn, *key_dates.fetch("UBCV"))  # public, no login - always shown, sample or real
now = datetime.now(timezone.utc)

tab_all, tab_tasks, tab_deadlines, tab_materials, tab_textbooks = \
    st.tabs(["All", "Tasks", "Deadlines", "Materials", "Textbooks"])

for tab, category in zip([tab_all, tab_tasks, tab_deadlines, tab_materials], [None, "task", "deadline", "material"]):
    with tab:
        def status(r):
            item = Item(course=r[0], category=r[1], kind=r[2], title=r[3],
                        due=datetime.fromisoformat(r[4]), url=r[5], source="", done=bool(r[6]) if r[6] is not None else None)
            return status_of(item, now)

        # Completed items never show, regardless of the Hide overdue toggle -
        # nothing left to do about them.
        rows = [r for r in db.upcoming(conn, category)
                if status(r) != "done" and (not hide_overdue or status(r) != "overdue")]
        rows = sort_items(rows, now)[:n]
        if not rows:
            st.info("Nothing upcoming." if demo else "Nothing yet. Connect Canvas in the sidebar.")
            continue
        st.dataframe(
            [{"Urgency": classify_urgency(r[3], datetime.fromisoformat(r[4]), now).capitalize(),
              "Due": datetime.fromisoformat(r[4]).astimezone(), "Course": r[0], "What": r[3], "Kind": r[2], "Link": r[5]}
             for r in rows],
            column_config={"Due": st.column_config.DatetimeColumn(format="ddd MMM D, h:mm a"),
                           "Link": st.column_config.LinkColumn(display_text="open")},
            hide_index=True, use_container_width=True,
        )

# ---------------------------------------------------------------------------
# Textbooks (#5/#6/#7): no setup needed - looked up automatically from each
# known course's own code + term, the same two things Canvas/Workday already
# gave us. hub.bookstore.fetch() only ever touches that one course's own
# section(s), never its whole department (AGENTS.md rule 5: "never hammer it
# in a loop" - a department can have dozens of sections). Cached 24h per
# course (design.md: Bookstore data is cached per term).
# ---------------------------------------------------------------------------
with tab_textbooks:
    st.caption("Looked up automatically from each of your courses - nothing to type in.")
    if st.button("🔍 Look up textbooks"):
        with st.spinner("Checking the Bookstore…"):
            for code, term, _title, _grade in db.courses(conn):
                if not term:
                    continue
                matched_course, found = _bookstore_lookup(code, term)
                # db.save() only matches a textbook to a course_id from the
                # `courses` list given in this SAME call (hub/db.py's `ids`
                # dict) - it doesn't look up an already-saved course from an
                # earlier call. Passing just textbooks= here silently
                # orphaned every one of them.
                db.save(conn, courses=matched_course, textbooks=found)
        # No st.rerun() here: in demo mode `conn` is an in-memory sample_conn()
        # rebuilt fresh on every rerun (see sample_conn()'s own docstring) - a
        # rerun would wipe out what was just saved before this same script
        # pass gets to read it back below. Falling through to db.textbooks()
        # in this same run already sees it, with no double-render needed.

    books = db.textbooks(conn)
    if not books:
        st.info("No textbooks yet - click \"Look up textbooks\" above.")
    else:
        st.dataframe(
            [{"Course": code, "Book": title, "Required": "Yes" if required else "No",
              "Price": f"${price:.2f}" if price is not None else "?", "Link": url}
             for code, title, _isbn, required, price, url in books],
            column_config={"Link": st.column_config.LinkColumn(display_text="open")},
            hide_index=True, use_container_width=True,
        )


@st.dialog("Connect Workday")
def _workday_dialog():
    # ponytail: stub - hub/workday.py's parse_workday_courses() exists and is
    # tested, but nothing calls it yet. Wire up a real st.file_uploader() +
    # term input here (see design.md: student uploads their own "View My
    # Courses" export, there's no login/API path) when this becomes more
    # than a placeholder.
    st.write("Workday import isn't wired up yet.")
    st.caption("Coming soon: upload your \"View My Courses\" export from Workday to add your class schedule.")
    st.file_uploader("View My Courses.xlsx", type="xlsx", disabled=True)


st.divider()
if st.button("Connect Workday", help="Not implemented yet - opens a placeholder"):
    _workday_dialog()

# #18: one merged .ics feed a student can drop straight into Apple/Google/
# Outlook Calendar - the cheapest way into a routine they already have.
_export_items = [
    Item(course=r[0], category=r[1], kind=r[2], title=r[3],
         due=datetime.fromisoformat(r[4]), url=r[5], source=r[7])
    for r in db.upcoming(conn)
]
st.download_button(
    "Add to my calendar", data=export_ics.to_ics(_export_items),
    file_name="ubc-hub.ics", mime="text/calendar",
    help="One .ics file with every upcoming item - subscribe to it in Apple/Google/Outlook Calendar.",
)

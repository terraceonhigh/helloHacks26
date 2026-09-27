"""Demo frontend: what's due next, across every connected provider."""
from datetime import datetime, timedelta, timezone

import streamlit as st

from hub import canvas, db, export_ics, key_dates, prairielearn, workday
from hub.logic import sort_items
from hub.models import Course, Item, category_for, classify_urgency, status_of

st.set_page_config(page_title="Lauds", layout="wide")
st.title("Lauds")
st.caption("The first thing you check in the morning.")

# One glance at "Urgency" as text still means reading every row - a marker
# column makes the ranking visible without reading anything (hub.models
# already defines this exact 5-level scale via classify_urgency/status_of).
URGENCY_MARKER = {"overdue": "🔴", "critical": "🟠", "high": "🟡", "medium": "🔵", "low": "⚪"}


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


def _row_item(r):
    """A hub.db.upcoming()/undated() row - (code, category, kind, title, due,
    url, done, source) - back as a real Item. One place to do this instead of
    repeating datetime.fromisoformat(r[4]) and the same field-by-field
    unpacking at every call site (status_of, classify_urgency, the calendar
    export all used to redo it separately)."""
    return Item(course=r[0], category=r[1], kind=r[2], title=r[3],
                due=datetime.fromisoformat(r[4]) if r[4] else None, url=r[5],
                source=r[7], done=bool(r[6]) if r[6] is not None else None)


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

tab_all, tab_tasks, tab_deadlines, tab_materials, tab_courses = \
    st.tabs(["All", "Tasks", "Deadlines", "Materials", "Courses"])

for tab, category in zip([tab_all, tab_tasks, tab_deadlines, tab_materials], [None, "task", "deadline", "material"]):
    with tab:
        # Completed items never show, regardless of the Hide overdue toggle -
        # nothing left to do about them.
        rows = []
        for r in db.upcoming(conn, category):
            state = status_of(_row_item(r), now)
            if state == "done" or (hide_overdue and state == "overdue"):
                continue
            rows.append(r)
        rows = sort_items(rows, now)[:n]
        if not rows:
            st.info("Nothing upcoming." if demo else "Nothing yet. Connect Canvas in the sidebar.")
            continue

        table = []
        for r in rows:
            item = _row_item(r)
            urgency = classify_urgency(item.title, item.due, now)
            table.append({
                "": URGENCY_MARKER[urgency], "Urgency": urgency.capitalize(),
                "Due": item.due.astimezone(), "Course": item.course, "What": item.title,
                "Kind": item.kind, "Link": item.url,
            })
        st.dataframe(
            table,
            column_config={"": st.column_config.TextColumn(width="small"),
                           "Due": st.column_config.DatetimeColumn(format="ddd MMM D, h:mm a"),
                           "Link": st.column_config.LinkColumn(display_text="open")},
            hide_index=True, use_container_width=True,
        )

# ---------------------------------------------------------------------------
# Courses (#10): every course we know about, with its current grade (Canvas
# only) and how many upcoming items it has - the "one card per course"
# summary the item tables above don't give you.
# ---------------------------------------------------------------------------
with tab_courses:
    courses = db.courses(conn)
    if not courses:
        st.info("No courses yet." if demo else "Nothing yet. Connect Canvas in the sidebar.")
    else:
        upcoming_counts = {code: len(rows) for code, rows in db.by_course(conn).items()}
        columns = st.columns(3)
        for index, (code, term, title, grade) in enumerate(courses):
            with columns[index % 3], st.container(border=True):
                st.subheader(code)
                st.caption(f"{title} · {term}" if term else title)
                if grade is not None:
                    st.metric("Grade", f"{grade:.1f}%")
                count = upcoming_counts.get(code, 0)
                st.caption(f"{count} upcoming item{'s' if count != 1 else ''}")


@st.dialog("Connect Workday")
def _workday_dialog():
    st.write("Upload your \"View My Courses\" export to add your class schedule.")
    term = st.text_input("Term", value="2026W1", help="UBC's short term code, e.g. 2026W1")
    uploaded = st.file_uploader("View My Courses.xlsx", type="xlsx")
    if uploaded is not None and st.button("Import"):
        courses = workday.parse_workday_courses(uploaded, term)
        if not courses:
            st.warning("No courses found - check it's the \"View My Courses\" export.")
        else:
            db.save(db.connect(), courses)
            st.success(f"Imported {len(courses)} course(s). Turn off \"Sample data\" in the sidebar to see them.")


st.divider()
if st.button("Connect Workday"):
    _workday_dialog()

# #18: one merged .ics feed a student can drop straight into Apple/Google/
# Outlook Calendar - the cheapest way into a routine they already have.
st.download_button(
    "Add to my calendar", data=export_ics.to_ics([_row_item(r) for r in db.upcoming(conn)]),
    file_name="ubc-hub.ics", mime="text/calendar",
    help="One .ics file with every upcoming item - subscribe to it in Apple/Google/Outlook Calendar.",
)

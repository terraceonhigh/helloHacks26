"""Demo frontend: what's due next, across every connected provider."""
from datetime import datetime, timedelta, timezone

import streamlit as st

from hub import canvas, db, prairielearn
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
    titles = {"CPSC 121": ("Models of Computation", 84.5), "MATH 100": ("Differential Calculus", 71.0),
              "ENGL 110": ("Approaches to Literature", None)}
    courses = [Course(code=c, section="101", term="2026W1", title=ti, grade=g) for c, (ti, g) in titles.items()]
    items = [Item(course=c, category=category_for(k), kind=k, title=t, due=now + timedelta(days=d),
                  url=f"https://example.invalid/{n}", source="sample") for n, (c, t, k, d) in enumerate(rows)]
    conn = db.connect(":memory:")
    db.save(conn, courses, items)
    return conn


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
now = datetime.now(timezone.utc)

def overdue(r):
    item = Item(course=r[0], category=r[1], kind=r[2], title=r[3],
                due=datetime.fromisoformat(r[4]), url=r[5], source="", done=bool(r[6]) if r[6] is not None else None)
    return status_of(item, now) == "overdue"


def visible(rows):
    """Hide overdue if asked, then rank most urgent first. Shared by every tab."""
    return sort_items([r for r in rows if not hide_overdue or not overdue(r)], now)


def table(rows):
    st.dataframe(
        [{"Urgency": classify_urgency(r[3], datetime.fromisoformat(r[4]), now).capitalize(),
          "Due": datetime.fromisoformat(r[4]).astimezone(), "Course": r[0], "What": r[3], "Kind": r[2], "Link": r[5]}
         for r in rows],
        column_config={"Due": st.column_config.DatetimeColumn(format="ddd MMM D, h:mm a"),
                       "Link": st.column_config.LinkColumn(display_text="open")},
        hide_index=True, use_container_width=True,
    )


*category_tabs, courses_tab = st.tabs(["All", "Tasks", "Deadlines", "Materials", "Courses"])
for tab, category in zip(category_tabs, [None, "task", "deadline", "material"]):
    with tab:
        rows = visible(db.upcoming(conn, category))[:n]
        if rows:
            table(rows)
        else:
            st.info("Nothing upcoming." if demo else "Nothing yet. Connect Canvas in the sidebar.")

with courses_tab:
    grouped = db.by_course(conn)
    for code, term, title, grade in db.courses(conn):
        rows = visible(grouped.get(code, []))
        label = f"{code} · {title}" + (f" · {grade:.0f}%" if grade is not None else "")
        with st.expander(f"{label} ({len(rows)} upcoming)"):
            if rows:  # not a one-line ternary: Streamlit "magic" would st.write() its None
                table(rows)
            else:
                st.caption("Nothing upcoming.")

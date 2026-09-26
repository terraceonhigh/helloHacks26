"""UBC Hub -- Streamlit entry point.

UI only: rendering and st.session_state. No fetching or parsing here
(AGENTS.md) -- adapters live in hub/*.py, and the pure helpers behind these
screens live in hub/view.py so they can be pytest'd.
"""

import streamlit as st

from hub.sample import load_sample
from hub.view import badge, course_summary, flag, group_by_day, mask_secret

st.set_page_config(page_title="UBC Hub", page_icon="🎓", layout="wide")
st.title("UBC Hub")

courses, items, textbooks = load_sample()
course_code_by_key = {c.key: c.code for c in courses}

tab_week, tab_courses, tab_setup = st.tabs(["This week", "Courses", "Setup"])

# ---------------------------------------------------------------------------
# This week (#9): Items sorted by due date, badged by source.
# ---------------------------------------------------------------------------
with tab_week:
    overdue_count = sum(1 for i in items if flag(i) == "overdue")
    soon_count = sum(1 for i in items if flag(i) == "soon")
    st.caption(f"{soon_count} due soon, {overdue_count} overdue")

    all_course_codes = sorted(set(course_code_by_key.values()))
    picked_codes = st.multiselect("Filter by course", all_course_codes, default=all_course_codes)

    visible_items = [
        item
        for item in items
        if item.course_key is None or course_code_by_key.get(item.course_key) in picked_codes
    ]

    if not visible_items:
        st.info("Nothing matches this filter.")

    for day, day_items in group_by_day(visible_items):
        st.subheader(f"{day:%a, %b} {day.day}" if day else "No due date")
        for item in day_items:
            state = flag(item)
            marker = {"overdue": "🔴", "soon": "🟠"}.get(state, "⚪")
            code = course_code_by_key.get(item.course_key, item.course_key or "")
            label = f"**{item.title}**" + (f" — {code}" if code else "")

            col_marker, col_title, col_badge = st.columns([1, 6, 2])
            col_marker.write(marker)
            col_title.markdown(f"[{label}]({item.url})" if item.url else label)
            col_badge.caption(badge(item.source))

# ---------------------------------------------------------------------------
# Course card (#10): section, current grade, required textbooks + price.
# ---------------------------------------------------------------------------
with tab_courses:
    card_columns = st.columns(2)
    for index, course in enumerate(courses):
        summary = course_summary(course, textbooks)
        with card_columns[index % 2]:
            with st.container(border=True):
                st.subheader(f"{course.code} {course.section}")
                st.write(course.title)
                if course.grade is not None:
                    st.metric("Current grade", f"{course.grade:.1f}%")
                else:
                    st.caption("No grade yet")

                required = summary["required_textbooks"]
                if required:
                    st.write("**Required textbooks**")
                    for book in required:
                        price = f"${book.price_new:.2f}" if book.price_new is not None else "price unknown"
                        st.write(f"- {book.title} ({price})")
                    if summary["required_total"] is not None:
                        st.caption(f"Required total: ${summary['required_total']:.2f}")
                else:
                    st.caption("No required textbooks listed")

# ---------------------------------------------------------------------------
# Setup (#11): collect Canvas token/feed URL and a Workday export, hand off
# to the logic layer. Never write a token or feed URL to disk (AGENTS.md).
# ---------------------------------------------------------------------------
with tab_setup:
    st.write("Connect your own sources. Nothing here is stored anywhere but this browser tab's session.")

    st.subheader("Canvas")
    canvas_mode = st.radio(
        "Canvas access", ["Personal access token", "Calendar feed URL (no token)"], horizontal=True
    )
    field_label = "Canvas personal access token" if canvas_mode.startswith("Personal") else "Canvas calendar feed URL"
    canvas_credential = st.text_input(field_label, type="password", key="canvas_credential_input")
    if canvas_credential:
        st.session_state["canvas_credential"] = {"mode": canvas_mode, "value": canvas_credential}
        st.caption(f"Using: {mask_secret(canvas_credential)}")

    st.subheader("Workday")
    workday_file = st.file_uploader("View My Courses export (.xlsx)", type=["xlsx"])
    if workday_file is not None:
        st.session_state["workday_file"] = workday_file
        st.caption(f"Received {workday_file.name} -- not saved to disk.")
        st.info("Workday import isn't built yet (tracked in #2). This just collects the upload for now.")

    st.subheader("Bookstore")
    st.caption("No setup needed -- looked up automatically from your course sections.")

    st.divider()
    st.caption("If you can see this, your setup works. Next: pick an issue on GitHub.")

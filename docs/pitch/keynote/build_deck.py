import sys
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

IMG, OUT = sys.argv[1], sys.argv[2]
ACC, ACCD, INK, BODY, MUTED = "B84028", "98331F", "17211B", "46524C", "5F6B65"
BG, CARD, LINE, TILE, CREAM, PINK, SOFT, TINT = "F7F8F6", "FFFFFF", "E4E9E5", "E39A35", "FFF8F4", "F3D9CE", "FBE4DA", "FDF2EC"
FONT = "Arial"

prs = Presentation(); prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]
rgb = lambda h: RGBColor.from_string(h)

def slide(bg=BG):
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid(); s.background.fill.fore_color.rgb = rgb(bg)
    return s

def para(tf, text, size, color, bold=False, italic=False, align=PP_ALIGN.LEFT, first=False, spc=None, after=0):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align; p.space_after = Pt(after)
    r = p.add_run(); r.text = text
    f = r.font; f.name, f.size, f.bold, f.italic = FONT, Pt(size), bold, italic; f.color.rgb = rgb(color)
    if spc: r._r.get_or_add_rPr().set("spc", str(spc))
    return p

def text(s, x, y, w, h, lines, anchor=MSO_ANCHOR.TOP):
    """lines: list of (text, size, color, opts dict)."""
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)); tf = tb.text_frame
    tf.word_wrap = True; tf.vertical_anchor = anchor
    for m in ("margin_left", "margin_right", "margin_top", "margin_bottom"): setattr(tf, m, 0)
    for i, (t, size, color, o) in enumerate(lines): para(tf, t, size, color, first=(i == 0), **o)
    return tb

def box(s, x, y, w, h, fill=CARD, line=LINE, lines=(), anchor=MSO_ANCHOR.TOP, pad=0.22, radius=0.08):
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.adjustments[0] = radius; sh.shadow.inherit = False
    sh.fill.solid(); sh.fill.fore_color.rgb = rgb(fill)
    if line: sh.line.color.rgb = rgb(line); sh.line.width = Pt(1)
    else: sh.line.fill.background()
    tf = sh.text_frame; tf.word_wrap = True; tf.vertical_anchor = anchor
    for m in ("margin_left", "margin_right", "margin_top", "margin_bottom"): setattr(tf, m, Inches(pad))
    for i, (t, size, color, o) in enumerate(lines): para(tf, t, size, color, first=(i == 0), **o)
    return sh

def arrow(s, x, y, w, h, down=False, color=ACC):
    sh = s.shapes.add_shape(MSO_SHAPE.DOWN_ARROW if down else MSO_SHAPE.RIGHT_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid(); sh.fill.fore_color.rgb = rgb(color); sh.line.fill.background(); sh.shadow.inherit = False

def eyebrow(s, t, y=0.55, color=ACC): text(s, 0.8, y, 11.7, 0.35, [(t.upper(), 13, color, {"bold": True, "spc": 300})])
def title(s, t, y=0.95, size=36, color=INK, h=1.0): text(s, 0.8, y, 11.7, h, [(t, size, color, {"bold": True})])
def notes(s, t): s.notes_slide.notes_text_frame.text = t
C = PP_ALIGN.CENTER

# 1 Cover
s = slide(ACC)
text(s, 0.8, 1.55, 11.7, 0.4, [("UBC BIZTECH HELLOHACKS 2026", 16, PINK, {"bold": True, "spc": 400})])
text(s, 0.8, 2.0, 11.7, 1.9, [("Lauds", 120, CREAM, {"bold": True})])
text(s, 0.8, 4.15, 11.7, 0.6, [("The first thing you check in the morning.", 28, SOFT, {})])
notes(s, "Open with: \"Lauds: sensor fusion for student life. The first thing you check in the morning.\"\n\nSay the name slowly: L-A-U-D-S. Lauds is the old name for the morning prayer, the first thing you do each day.\n\nThe one-breath version, if asked what it is: A UBC student's week is spread across nine systems that never talk to each other. Lauds treats each one as a sensor, fuses them into one shared model, and shows one ranked picture of what's due, where to be and what's at risk.")

# 2 Meet Stu
s = slide()
title(s, "Meet Stu.", y=0.6, size=44)
text(s, 0.8, 1.6, 11.3, 1.2, [("He has a Canvas account, a Piazza account, a WeBWorK account, and several PrairieLearns with different domains. Is he keeping up with all those websites? No. In fact, he's already missed a few assignments.", 20, BODY, {})])
cards = [("Missed deadlines", "A quiz posted on WeBWorK never shows up on Canvas's calendar at all."),
         ("Scattered tools", "Piazza, Ed Discussion, Crowdmark, Moodle: a different app per course, sometimes per assignment."),
         ("Surprise costs", "Nobody checks the Bookstore until week 2, when the required textbook is $300."),
         ("Platform isolation", "Every platform is its own island. Nothing answers \"what do I need to do right now?\"")]
for i, (h, b) in enumerate(cards):
    box(s, 0.8 + i * 3.0, 3.35, 2.75, 2.7, lines=[(h, 18, INK, {"bold": True, "after": 8}), (b, 14, BODY, {})], pad=0.25)
notes(s, "Stu is the demo student you'll see on the live site. In one term Stu has Canvas for most courses, PrairieLearn for CPSC homework, WeBWorK for math, Piazza or Ed for discussion, Workday for the timetable, and the Bookstore for textbooks.\n\nWalk the four cards left to right. Each is a concrete failure.\n\nEnd on: \"The problem isn't missing information. It's scattered information. Each platform is a sensor with a narrow field of view, and nothing combines them.\"")

# 3 Solution
s = slide()
eyebrow(s, "Why?")
title(s, "Every platform is a sensor. Lauds fuses them.", size=40)
text(s, 0.8, 2.65, 11.0, 1.4, [("Lauds reads each system a student already uses, translates it into one shared model, and fuses it: duplicates merged, courses matched, everything ranked by what needs attention today, with a link back to where it lives.", 20, BODY, {})])
cols = [("SENSORS", "Canvas, Workday, Bookstore, Piazza...", CARD, MUTED, INK, LINE),
        ("FUSION", "Courses, Tasks, Announcements, Materials", ACC, PINK, CREAM, None),
        ("ONE PICTURE", "Dashboard", CARD, MUTED, INK, LINE)]
for i, (lab, body, fill, lc, bc, ln) in enumerate(cols):
    box(s, 0.8 + i * 4.1, 4.55, 3.5, 1.9, fill=fill, line=ln, anchor=MSO_ANCHOR.MIDDLE,
        lines=[(lab, 13, lc, {"bold": True, "align": C, "spc": 200, "after": 8}), (body, 19, bc, {"bold": True, "align": C})])
for x in (4.4, 8.5): arrow(s, x, 5.3, 0.5, 0.4)
notes(s, "This is the value proposition. Pause here.\n\nSay: \"We don't replace any of these systems. We read them all, translate them into one shared model, and fuse them.\"\n\nThe three boxes, left to right: the sensors are the systems students already use; fusion happens on one shared model (courses, tasks, announcements, materials); what comes out is one picture, the dashboard.\n\nThe proof you'll show in the demo: the same quiz posted on Canvas and PrairieLearn shows up once, not twice.")

# 4 How the sensors come together
s = slide()
eyebrow(s, "How the sensors come together", y=0.35)
title(s, "Many narrow sensors, one fused picture.", y=0.65, size=28, h=0.6)
sensors = ["Canvas", "PrairieLearn", "WeBWorK", "Piazza", "Workday", "Bookstore"]
text(s, 0.8, 1.3, 7.4, 0.3, [("SENSORS: THE SYSTEMS A STUDENT ALREADY USES", 11, MUTED, {"bold": True, "spc": 150})])
for i, n in enumerate(sensors):
    box(s, 0.8 + i * 1.25, 1.65, 1.15, 0.55, lines=[(n, 12, INK, {"bold": True, "align": C})], anchor=MSO_ANCHOR.MIDDLE, pad=0.04, radius=0.2)
layers = [(2.6, 0.75, "Adapters: one plug-in per sensor", "Each turns that system's raw data into the shared model", CARD, INK, BODY, LINE),
          (3.6, 0.75, "Shared model: the ontology", "Course, Item, Textbook: every source speaks the same language", CARD, INK, BODY, LINE),
          (4.6, 0.9, "Fusion: the cross-source join", "Match course codes, merge duplicates, rank by urgency, flag overdue work", CARD, INK, BODY, LINE),
          (5.75, 0.8, "One operating picture", "Overview, Calendar, Schedule, and a calendar feed for your phone", ACC, CREAM, SOFT, None)]
ys = [2.2] + [y + h for y, h, *_ in layers[:-1]]
for (y, h, n, l, fill, nc, lc, ln), top in zip(layers, ys):
    arrow(s, 4.35, top + 0.06, 0.3, y - top - 0.1, down=True, color="C9CFC9")
    box(s, 0.8, y, 7.4, h, fill=fill, line=ln, anchor=MSO_ANCHOR.MIDDLE, pad=0.15,
        lines=[(n, 15, nc, {"bold": True, "align": C, "after": 2}), (l, 12, lc, {"align": C})])
box(s, 8.75, 1.65, 3.8, 4.9, fill=TINT, line=None, pad=0.35, anchor=MSO_ANCHOR.MIDDLE,
    lines=[("THE IDEA", 12, ACC, {"bold": True, "spc": 200, "after": 14}),
           ("\"Nine systems, nine logins, nine separate habits. We fuse them into one morning check.\"", 20, INK, {"italic": True, "after": 14}),
           ("The fusion layer is the product, not any single connector.", 14, BODY, {})])
notes(s, "Replaced by the timed script below.")

# 5 Product demo
s = slide()
title(s, "Product demo", y=0.5, size=36, h=0.7)
for i, (img, h, b) in enumerate([("lauds-web-home.png", "Every deadline, one ranked list", "Top assignments across every platform, ranked by real urgency, not just a due-date sort."),
                                 ("lauds-web-calendar.png", "One calendar, every course", "A real month grid, not a list, and it exports as a calendar feed for Apple, Google or Outlook.")]):
    x = 0.8 + i * 6.0
    pic = s.shapes.add_picture(f"{IMG}/{img}", Inches(x), Inches(1.45), Inches(5.7), Inches(3.5625))
    pic.line.color.rgb = rgb(LINE); pic.line.width = Pt(1)
    text(s, x, 5.2, 5.7, 1.3, [(h, 18, INK, {"bold": True, "after": 6}), (b, 14, BODY, {})])
notes(s, "Two real screenshots of the web app. If you're doing the live demo, switch to the browser here: hello-hacks26-terraceonhigh.vercel.app. It opens on the demo student, no login.\n\nLeft: the ranked list. Top assignments across every course and platform, overdue first, ranked by urgency, not just date.\n\nRight: the calendar. A month grid across every course, and one calendar feed that puts every deadline in Apple, Google or Outlook Calendar.")

# 6 NEW demo in six clicks
s = slide()
eyebrow(s, "Live demo", y=0.5)
title(s, "The demo in six clicks", y=0.85, size=32, h=0.7)
steps = [("Overview", "About 25 due this week, 5 overdue. One picture before any other tab."),
         ("Top assignments", "The five most urgent across every course, ranked by urgency. Each links back to its platform."),
         ("Assignments", "Quiz 3 was posted on Canvas and PrairieLearn. It shows once: that's fusion."),
         ("Calendar, then Monday", "A lecture, a lab and about 11 deadlines from four platforms, in one list."),
         ("Schedule", "The weekly timetable from Workday, next to the work it's for."),
         ("Settings, Connections", "Every sensor is a plug-in. A new platform or school is one adapter.")]
for i, (h, b) in enumerate(steps):
    x, y = 0.8 + (i % 3) * 4.0, 1.85 + (i // 3) * 2.45
    box(s, x, y, 3.75, 2.2, pad=0.25, lines=[("", 8, INK, {}), (h, 17, INK, {"bold": True, "after": 6}), (b, 13, BODY, {})])
    c = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + 0.25), Inches(y + 0.25), Inches(0.5), Inches(0.5))
    c.fill.solid(); c.fill.fore_color.rgb = rgb(ACC); c.line.fill.background(); c.shadow.inherit = False
    tf = c.text_frame; [setattr(tf, m, 0) for m in ("margin_left", "margin_right", "margin_top", "margin_bottom")]
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE; para(tf, str(i + 1), 16, CREAM, bold=True, align=C, first=True)
    # push the card's text below the number
    box_tf = s.shapes[-2].text_frame; box_tf.margin_top = Inches(0.85)
text(s, 0.8, 6.8, 11.7, 0.35, [("hello-hacks26-terraceonhigh.vercel.app  ·  opens on a made-up demo student, week 5 of a 13-week term", 12, MUTED, {})])
notes(s, "NEW SLIDE. Your click path for the live demo. Counts shift slightly by weekday.\n\n1. Overview: point at the tiles. \"Nine sensors, one picture. This is what Stu sees before opening any other tab.\"\n2. Top assignments: \"Ranked by urgency, not just by date.\" Each row's icon opens the item on its own platform, so Lauds is the front door, not a replacement.\n3. Assignments tab: find Quiz 3 and WeBWorK 5. \"This quiz was posted on both Canvas and PrairieLearn. The fusion layer shows it once.\" Slow down here: it's the sensor-fusion proof.\n4. Calendar, click Monday: \"Where to be and what's due, fused.\"\n5. Schedule: \"Workday is a sensor too.\"\n6. Settings, Connections, briefly: \"Each one is a plug-in.\" The rows read 'Not connected' on purpose; the demo student is fake. Don't click Connect on stage.\n\nIf the site is down, play the recorded video.")

# 7 Architecture
s = slide()
eyebrow(s, "How it works", y=0.45)
title(s, "One shared model for every sensor.", y=0.8, size=34, h=0.7)
cx = 13.333 / 2
box(s, cx - 4.0, 1.75, 8.0, 1.15, anchor=MSO_ANCHOR.MIDDLE, pad=0.15,
    lines=[("Any Sensor", 18, INK, {"bold": True, "align": C, "after": 4}),
           ("Canvas · Workday · UBC Bookstore · Brightspace · WeBWorK · PrairieLearn, with 8 more coming", 13, MUTED, {"align": C})])
arrow(s, cx - 0.15, 2.95, 0.3, 0.4, down=True)
box(s, cx - 2.75, 3.4, 5.5, 0.95, fill=ACC, line=None, anchor=MSO_ANCHOR.MIDDLE, lines=[("Adapters and Fusion", 24, CREAM, {"bold": True, "align": C})])
arrow(s, cx - 0.15, 4.4, 0.3, 0.4, down=True)
box(s, cx - 2.1, 4.85, 4.2, 0.8, anchor=MSO_ANCHOR.MIDDLE, lines=[("Standardized Database", 18, INK, {"bold": True, "align": C})])
for x in (cx - 1.95, cx + 1.65): arrow(s, x, 5.7, 0.3, 0.4, down=True)
box(s, cx - 3.7, 6.15, 3.3, 0.8, anchor=MSO_ANCHOR.MIDDLE, lines=[("Lauds Web (Next.js)", 16, INK, {"bold": True, "align": C})])
box(s, cx + 0.4, 6.15, 3.3, 0.8, anchor=MSO_ANCHOR.MIDDLE, lines=[("Streamlit + .ics calendar feed", 15, INK, {"bold": True, "align": C})])
notes(s, "Read it top down: any sensor comes in, an adapter translates it and fusion runs on the shared model, it's stored in one standard database, and it comes out as the web app and a calendar feed.\n\nThe line to land: \"A new platform is one adapter file. The fusion, ranking and screens never change.\"\n\nIf asked what's in the database: three kinds of thing, a Course, an Item (anything due or announced) and a Textbook. Every item's identity is its source plus its link, which is what lets duplicates merge.")

# 8 Breadth
s = slide()
title(s, "14 platforms in the pipeline. 1 student who never has to think about which one.", y=0.5, size=30, h=1.2)
live = ["Canvas", "Workday", "UBC Bookstore", "PrairieLearn", "WeBWorK", "Brightspace"]
review = ["Moodle", "Blackboard", "Piazza", "Ed Discussion", "Google Classroom", "Crowdmark", "Macmillan Achieve", "Pearson MyLab"]
for i, n in enumerate(live + review):
    x, y = 0.85 + (i % 7) * 1.68, 2.05 + (i // 7) * 1.55
    on = i < len(live)
    box(s, x, y, 1.55, 1.35, fill=TILE if on else CARD, line=None if on else LINE, anchor=MSO_ANCHOR.MIDDLE, pad=0.08,
        lines=[(n, 13, INK if on else BODY, {"bold": True, "align": C})])
for j, (fill, ln, lab) in enumerate([(TILE, None, "Live on main today"), (CARD, "B9C2BC", "Built, in review")]):
    x = 0.85 + j * 2.9
    sw = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(5.3), Inches(0.28), Inches(0.28))
    sw.fill.solid(); sw.fill.fore_color.rgb = rgb(fill); sw.shadow.inherit = False
    if ln: sw.line.color.rgb = rgb(ln)
    else: sw.line.fill.background()
    text(s, x + 0.4, 5.27, 2.4, 0.35, [(lab, 15, BODY, {})])
notes(s, "Orange tiles, \"live on main\": Canvas, Workday, UBC Bookstore, PrairieLearn, WeBWorK and Brightspace. Their adapter code is merged.\nWhite tiles, \"built, in review\": eight more, from Moodle to Pearson MyLab.\n\nIf a judge asks: \"live on main\" means merged code, not that every one connects to a real account today. With a real account, Canvas, PrairieLearn, Workday and UBC key dates work now; WeBWorK and Brightspace connect is in review.\n\nLand it with the headline: one student who never has to think about which one.")

# 9 NEW What's real today
s = slide()
eyebrow(s, "Status", y=0.45)
title(s, "What's real today", y=0.8, size=32, h=0.7)
rows = [("Sensor", "In the live demo", "With your own account today"),
        ("Canvas", "Yes", "Yes: log in on your laptop, or paste your calendar-feed link"),
        ("PrairieLearn", "Yes", "Yes: log in on your laptop"),
        ("Workday", "Yes, 9 class meetings", "Yes: import the Workday .xlsx export"),
        ("UBC key dates", "Yes", "Yes, public data"),
        ("WeBWorK, Brightspace", "Yes (Brightspace: courses only)", "In review"),
        ("Piazza", "Yes, as announcements", "Code exists, not yet proven on a live class"),
        ("UBC Bookstore", "Yes, 3 textbooks", "Links to the Bookstore's own CWL book list"),
        ("Moodle, Blackboard, and 5 more", "No", "Built or started, in review")]
tbl = s.shapes.add_table(len(rows), 3, Inches(0.8), Inches(1.7), Inches(11.7), Inches(5.0)).table
for c, w in enumerate((3.0, 3.4, 5.3)): tbl.columns[c].width = Inches(w)
for r, row in enumerate(rows):
    for c, val in enumerate(row):
        cell = tbl.cell(r, c); cell.fill.solid(); cell.fill.fore_color.rgb = rgb(ACC if r == 0 else (CARD if r % 2 else "F1F3F1"))
        tf = cell.text_frame; tf.paragraphs[0].text = ""
        para(tf, val, 14, CREAM if r == 0 else (INK if c == 0 else BODY), bold=(r == 0 or c == 0), first=True)
        cell.margin_left = cell.margin_right = Inches(0.15)
notes(s, "NEW SLIDE. Mostly for Q&A: have it ready, you may not need to present it.\n\nEvery sensor in the demo runs through real adapter code, but real-account use is narrower. Know which column you're talking about.\n\nIf pressed on WeBWorK or Brightspace: they're in the demo; live connect is in review. If pressed on sync across devices: that's next, the storage isn't switched on yet.")

# 10 Rigor
s = slide()
title(s, "Engineering discipline you can actually check.", y=0.6, size=34, h=0.8)
rig = [("Zero credential handling", "Every login opens a real, visible browser window the student signs into themselves. Our code never sees a password."),
       ("Structured data first", "Each platform's own JSON or API where one exists; a narrow page read only where none does. Never a password."),
       ("Honest about what's unverified", "Every adapter's own notes state what's a cited fact versus a reasoned guess, in plain words."),
       ("Failure never cascades", "One malformed course or a down server can't wipe out every other course's already-fetched data."),
       ("Verified against the real thing", "Built and tested against real UBC endpoints during the hackathon, not just against documentation."),
       ("Caught before it shipped", "A live test against the real Bookstore caught a bug that would have hammered an entire department with requests. Fixed before merge.")]
for i, (h, b) in enumerate(rig):
    x, y = 0.8 + (i % 3) * 4.0, 1.75 + (i // 3) * 2.55
    hot = i == 5
    box(s, x, y, 3.75, 2.3, fill=ACC if hot else CARD, line=None if hot else LINE, pad=0.25,
        lines=[(h, 17, CREAM if hot else INK, {"bold": True, "after": 8}), (b, 13, SOFT if hot else BODY, {})])
notes(s, "Keep this one quick; judges skim it. Pick two cards:\n- \"Our code never sees a password.\" The student logs in themselves, and the session stays on their laptop.\n- \"Caught before it shipped.\" A live test against the real Bookstore found a bug that would have flooded it with requests.\n\nIf asked \"do you scrape?\": structured data first. Each platform's own feed where one exists; PrairieLearn and WeBWorK have none, so it reads one narrow page the student is already signed into.")

# 11 Proof
s = slide(ACC)
eyebrow(s, "Testing process", y=0.55, color=PINK)
title(s, "Built fast. Verified for real.", y=0.95, size=40, color=CREAM)
stats = [("6", "platforms fully live on main today"), ("325", "automated tests, green in CI right now"),
         ("3", "real bugs caught by live-testing, before they ever shipped"), ("0", "student passwords ever seen, stored, or sent anywhere by our code")]
for i, (n, l) in enumerate(stats):
    box(s, 0.8 + i * 3.0, 2.4, 2.75, 3.6, fill="FDF4F0", line=None, anchor=MSO_ANCHOR.MIDDLE, pad=0.25,
        lines=[(n, 66, ACC, {"bold": True, "align": C, "after": 10}), (l, 14, BODY, {"align": C})])
notes(s, "Read the four numbers, one line each.\n- 6: platforms whose adapter code is merged.\n- 325: automated backend tests on the main code, all passing. (There are 49 web tests on top.)\n- 3: bugs caught by live testing. That's the team's own count; don't elaborate on it.\n- 0: passwords, by design.\n\nOther numbers you can quote from the demo: 195 raw records from nine sensors fuse into 76 items, across 6 courses, 9 weekly class meetings, 8 announcements and 3 textbooks.")

# 12 Roadmap
s = slide()
eyebrow(s, "What's next", y=0.55)
title(s, "Already in review, not just on a whiteboard.", size=36)
road = [("Hosted, synced store", "A cloud store so a student's dashboard follows them off device. In alpha now."),
        ("Zero-click capture", "A browser extension that syncs signed-in tabs automatically, so it works while you work."),
        ("Key information from syllabus", "An LLM reads the syllabus PDF for the exam date or assignment link a professor never put on Canvas."),
        ("Beyond UBC", "The model was built with extendability in mind from day one, to work anywhere.")]
for i, (h, b) in enumerate(road):
    box(s, 0.8 + i * 3.0, 2.5, 2.75, 2.9, pad=0.25, lines=[(h, 17, INK, {"bold": True, "after": 8}), (b, 13, BODY, {})])
notes(s, "These are next, not shipped. Say \"in review\" or \"next\", never \"it does\".\n\n- Synced store: the code is merged but the storage isn't switched on yet, so don't demo sync.\n- Zero-click capture: the extension exists; auto-sync to the hosted site depends on the synced store.\n- Syllabus: a proposal in review.\n- Beyond UBC: Moodle, Blackboard and Brightspace adapters are already started. A new school is one adapter.")

# 13 Thanks
s = slide(ACC)
text(s, 0.8, 1.7, 11.7, 1.4, [("Lauds.", 88, CREAM, {"bold": True})])
text(s, 0.8, 3.2, 10.0, 1.0, [("Every platform a university student already uses, fused into one shared model, ranked by what actually matters now.", 22, SOFT, {})])
for j, (lab, val) in enumerate([("CODE", "github.com/terraceonhigh/helloHacks26"), ("BUILT FOR", "UBC BizTech HelloHacks 2026")]):
    text(s, 0.8 + j * 4.6, 4.7, 4.4, 0.8, [(lab, 12, "F4C3B3", {"bold": True, "spc": 200, "after": 4}), (val, 17, CREAM, {})])
text(s, 0.8, 5.9, 8.0, 0.8, [("BY TEAM 26", 12, "F4C3B3", {"bold": True, "spc": 200, "after": 4}), ("Terrace, Jacky, Samaya & Vihaan", 17, CREAM, {})])
notes(s, "Close with: \"Every platform a student already uses, fused into one picture. Lauds: the first thing you check in the morning.\"\n\nThank the team by name. Check 'Samaya' before you present: it's the name the deck uses, and it hasn't been confirmed.\n\nThe live site is hello-hacks26-terraceonhigh.vercel.app if anyone wants to try it.")

# 14 Appendix: Q&A
s = slide()
eyebrow(s, "Appendix", y=0.45)
title(s, "Judge questions", y=0.8, size=32, h=0.7)
qa = [("Is this real data?", "The demo student is fake, built in each platform's real format and run through the same code that reads a real account."),
      ("Why not Canvas's calendar?", "Canvas only sees Canvas. A WeBWorK quiz never shows up there. The value is the join."),
      ("What's the moat?", "The shared model and the fusion on top. One connector is easy to copy; fusing nine is the product."),
      ("How does it scale to other schools?", "A new platform or school is one adapter file. Fusion, ranking and screens don't change."),
      ("Do you scrape?", "Each platform's own data feed where one exists; otherwise one narrow page the student is already signed into."),
      ("What about passwords?", "We never see them. You log in yourself, and the session stays on your laptop."),
      ("Why fusion, not another dashboard?", "Other dashboards show one platform. Lauds joins nine, so duplicates merge and one ranked list covers everything."),
      ("What's next?", "Sync across devices, capture from tabs you already have open, deadlines read from syllabus PDFs.")]
for col in range(2):
    tb = text(s, 0.8 + col * 6.05, 1.7, 5.65, 5.4, [])
    tf = tb.text_frame
    for k, (q, a) in enumerate(qa[col * 4:(col + 1) * 4]):
        para(tf, q, 15, ACC, bold=True, first=(k == 0), after=3)
        para(tf, a, 13, BODY, after=14)
notes(s, "APPENDIX. Keep this up during Q&A, or use it as a crib sheet.")

# 15 Appendix: claims
s = slide()
eyebrow(s, "Appendix", y=0.45)
title(s, "Keep these claims straight", y=0.8, size=32, h=0.7)
cl = [("Don't say", "Say instead"),
      ("\"It connects to WeBWorK and Brightspace.\"", "\"They're in the demo; live connect is in review.\""),
      ("\"Your dashboard syncs across devices.\"", "\"A synced account is next.\""),
      ("\"We support 14 platforms.\"", "\"14 in the pipeline: 6 merged, 8 in review.\""),
      ("\"Click to buy your textbooks.\"", "\"It shows your required textbooks.\""),
      ("\"We only ever read JSON.\"", "\"Structured data first, a narrow page read where there's no feed.\""),
      ("\"It's a Canvas tool.\"", "\"Canvas is the first sensor, not the product.\""),
      ("Comparisons to Palantir or military language", "\"Many narrow sensors, one fused picture.\"")]
tbl = s.shapes.add_table(len(cl), 2, Inches(0.8), Inches(1.7), Inches(11.7), Inches(4.6)).table
for c in range(2): tbl.columns[c].width = Inches(5.85)
for r, row in enumerate(cl):
    for c, val in enumerate(row):
        cell = tbl.cell(r, c); cell.fill.solid(); cell.fill.fore_color.rgb = rgb(ACC if r == 0 else (CARD if r % 2 else "F1F3F1"))
        tf = cell.text_frame; tf.paragraphs[0].text = ""
        para(tf, val, 15, CREAM if r == 0 else (MUTED if c == 0 else INK), bold=(r == 0 or c == 1), first=True)
        cell.margin_left = cell.margin_right = Inches(0.15)
notes(s, "APPENDIX, for you, not the audience. Also: record the demo video in Sample mode. Real data would show your actual courses and grades.")


# ---- 5-minute cut: loop slide, timed script in notes, backup slides to the appendix ----
s = slide()
eyebrow(s, "Why it works", y=0.5)
title(s, "A tight loop for every student's morning", y=0.85, size=32, h=0.7)
text(s, 0.8, 1.55, 11.7, 0.4, [("See it, fuse it, rank it, act on it: a tight four-step loop, run on a student's week.", 15, BODY, {})])
loop = [(0.8, 2.25, "SEE", "Read every sensor", "Canvas, PrairieLearn, WeBWorK, Piazza, Workday, the Bookstore", False),
        (5.0, 2.25, "FUSE", "Fuse into one model", "Match courses, merge duplicates: one quiz on two platforms is one item", True),
        (5.0, 4.85, "DECIDE", "Rank what matters", "Urgency from due date and kind, weighted by what matters to you", False),
        (0.8, 4.85, "ACT", "One click to do it", "Open it where it lives, check it off, or send it to your calendar", False)]
for x, y, lab, h, b, hot in loop:
    box(s, x, y, 3.4, 2.05, fill=ACC if hot else CARD, line=None if hot else LINE, pad=0.25,
        lines=[(lab, 12, PINK if hot else ACC, {"bold": True, "spc": 250, "after": 6}), (h, 18, CREAM if hot else INK, {"bold": True, "after": 6}), (b, 13, SOFT if hot else BODY, {})])
for shp, x, y, w, h in [(MSO_SHAPE.RIGHT_ARROW, 4.35, 3.05, 0.5, 0.4), (MSO_SHAPE.DOWN_ARROW, 6.5, 4.35, 0.4, 0.45),
                        (MSO_SHAPE.LEFT_ARROW, 4.35, 5.65, 0.5, 0.4), (MSO_SHAPE.UP_ARROW, 2.3, 4.35, 0.4, 0.45)]:
    a = s.shapes.add_shape(shp, Inches(x), Inches(y), Inches(w), Inches(h))
    a.fill.solid(); a.fill.fore_color.rgb = rgb(ACC); a.line.fill.background(); a.shadow.inherit = False
box(s, 8.9, 2.25, 3.6, 4.65, fill=TINT, line=None, pad=0.35, anchor=MSO_ANCHOR.MIDDLE,
    lines=[("Most student tools stop at reading.", 22, INK, {"bold": True, "after": 12}),
           ("Lauds closes the loop, every morning, before you open any other tab.", 16, BODY, {})])

SCRIPT = {
 0: ("0:00", 15, "Hi, I'm Terrace from Team 26. This is Lauds: sensor fusion for student life. It's the first thing you check in the morning."),
 1: ("0:15", 35, "Meet Stu. Stu has Canvas, Piazza, WeBWorK, and a couple of PrairieLearns on different domains. Workday has his timetable. The Bookstore has his textbooks. None of them talk to each other. So a quiz posted on WeBWorK never shows up on Canvas's calendar. A three-hundred-dollar textbook turns up in week two. And nothing can answer the one question Stu has every morning: what do I need to do right now?"),
 2: ("0:50", 30, "Here's our idea. Every one of those platforms is a sensor. Each one sees its own slice of Stu's week, and nothing more. Lauds doesn't replace any of them. It reads them all, translates them into one shared model, and fuses them: duplicates merged, courses matched, everything ranked by what needs attention today."),
 3: ("1:20", 35, "Here's how the sensors come together. Across the top are the systems Stu already uses: nine systems, nine logins, nine separate habits. Each one gets a small adapter that translates it into one shared model: courses, items and textbooks. Fusion only happens on that model. That's how CPSC underscore V 110 in Canvas and CPSC 110 in Piazza become one course. We fuse them into one morning check. The fusion layer is the product, not any single connector."),
 15: ("1:55", 35, "And it runs as a tight loop, every morning. See it: read every sensor. Fuse it: one model, so one quiz on two platforms is one item. Decide: rank by urgency, weighted by what matters to you. Act: one click opens it where it lives, or checks it off. Most student tools stop at reading. Lauds closes the loop, before you open any other tab."),
 5: ("2:30", 75, "Let me show you. [Switch to the browser.] This is the live site. No login: it's a made-up student in week five. [Overview] Twenty-five things due this week, five already overdue, ranked across every course. [Top assignments] The five most urgent, overdue first, and each one links straight back to the platform it came from. [Assignments tab] Here's Quiz 3. It was posted on both Canvas and PrairieLearn, and it shows up once. That's fusion. [Calendar, click Monday] Monday: a lecture, a lab and eleven deadlines from four platforms, on one screen. [Schedule tab] His timetable, straight from Workday. [Settings] And every one of these sensors is a plug-in. [Switch back to the slides.]"),
 6: ("3:45", 15, "Under the hood: any sensor, one adapter, one standard database, out to the web app and a calendar feed for your phone. A new platform is one adapter file."),
 7: ("4:00", 15, "Six platforms are merged today, and eight more are built and in review. Fourteen in the pipeline, and one student who never has to think about which one."),
 9: ("4:15", 15, "We held ourselves to rules you can check. Students log in themselves, so our code never sees a password. And a live test against the real Bookstore caught a bug before it shipped."),
 10: ("4:30", 15, "In numbers: six platforms, three hundred and twenty-five automated tests, three bugs caught live, and zero passwords."),
 11: ("4:45", 15, "Next: a synced account so it follows you across devices, capture from tabs you already have open, and deadlines read straight from syllabus PDFs."),
 12: ("5:00", 15, "Every platform a student already uses, fused into one picture, before you open any other tab. That's Lauds: the first thing you check in the morning. Thank you."),
}
CUT = {9: "If you're running long, cut this slide.", 10: "If you're running long, merge this into the previous line.", 11: "If you're running long, say only the first item."}
BACKUP = {4: "APPENDIX (backup). If the live demo fails, jump here and talk over the two screenshots with the same lines as the demo.",
          8: "APPENDIX. For Q&A only: which sensors work with a real account today."}
slides = list(prs.slides)
for i, (start, secs, line) in SCRIPT.items():
    words = len(line.replace("[", " [").split())
    extra = ("\n\nTiming: " + CUT[i]) if i in CUT else ""
    slides[i].notes_slide.notes_text_frame.text = (f"[{start}, about {secs}s]\n\n{line}{extra}\n\n---\nBackground: " +
        {0: "Say the name slowly: L-A-U-D-S. Lauds is the old name for the morning prayer.",
         1: "Stu is the demo student on the live site.",
         2: "The value proposition. Pause after 'fuses them'.",
         3: "The ontology is the one shared vocabulary every source is translated into. If asked: Course, Item (anything due or announced), Textbook.",
         15: "Fuse is highlighted because fusion is the product.",
         5: "Counts shift slightly by weekday. The Connections rows read 'Not connected' on purpose; don't click Connect on stage. If the site is down, go to the backup slide in the appendix.",
         6: "Every item's identity is its source plus its link; that's what lets duplicates merge.",
         7: "Orange means merged code. With a real account today: Canvas, PrairieLearn, Workday, key dates. WeBWorK and Brightspace connect is in review.",
         9: "If asked 'do you scrape?': structured data first; PrairieLearn and WeBWorK have no feed, so one narrow page read.",
         10: "325 is the backend test count on main; 49 web tests on top. The 3-bugs figure is the team's own count.",
         11: "These are next, not shipped. Don't demo sync.",
         12: "Thank the team by name. Check 'Samaya' before presenting."}[i])
for i, t in BACKUP.items():
    slides[i].notes_slide.notes_text_frame.text = t + "\n\n" + slides[i].notes_slide.notes_text_frame.text
ORDER = [0, 1, 2, 3, 15, 5, 6, 7, 9, 10, 11, 12, 4, 8, 13, 14]
lst = prs.slides._sldIdLst; ids = list(lst)
for el in ids: lst.remove(el)
for i in ORDER: lst.append(ids[i])
import re as _re; total_words = sum(len(_re.sub(r"\[[^\]]*\]", "", v[2]).split()) for v in SCRIPT.values()); total_secs = sum(v[1] for v in SCRIPT.values())
print(f"script: {total_words} spoken words (~{total_words/150:.1f}-{total_words/130:.1f} min of speech), planned {total_secs//60}:{total_secs%60:02d}")

prs.save(OUT); print("saved", OUT, len(prs.slides), "slides")

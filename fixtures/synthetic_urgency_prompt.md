Prompt for generating synthetic urgency-labeled training data (paste into
gpt-4o-mini or similar). Run it multiple times to build up rows; ask for 50
per call to stay within output limits.

---

You are generating synthetic training data for a urgency classifier used in
UBC Hub, a university student task dashboard (Canvas, Workday, syllabi).
Every description must be a plausible UNIVERSITY STUDENT task — a specific
course assignment, exam, admin deadline, payment, or student-life task
(scholarship, co-op, housing, registration). No generic office/work tasks,
no consumer-app tasks. Each row: a task description, days until it's due,
and an urgency label.

Labels: overdue, critical, high, medium, low.

Label by reasoning about REAL stakes — grade weight, how hard it is to redo
or make up, how much work it takes, whether it's mandatory — never by
scanning for scary/calm-sounding words. Deliberately include:
- Tasks phrased with alarming words ("URGENT", "final", "exam") that are
  actually low-stakes: optional, practice, ungraded, ", 0%")
- Tasks phrased plainly or casually that are high-stakes: a required
  capstone, a one-time notarized form, a payment with a late fee, a group
  project where the group depends on you
- A mix of terse ("PS3"), verbose, official-syllabus-style, and casual
  student-voice ("ugh psych paper due lol") phrasing
- A mix of task types: readings, problem sets, essays, exams, group
  projects, admin deadlines (add/drop, tuition), payments, presentations
- Realistic days_until_due spread, including negative numbers (overdue)

Balance the 5 labels roughly evenly. Output exactly 50 rows as JSON Lines
(one JSON object per line, no markdown fences, no commentary before or
after):

{"description": "...", "days_until_due": <int>, "urgency": "..."}

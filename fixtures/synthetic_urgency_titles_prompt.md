Prompt for generating a synthetic TITLE-ONLY urgency test set (paste into
gpt-4o-mini or similar; run in batches of 50).

Unlike the earlier synthetic_urgency_prompt.md set, this matches what UBC
Lauds actually has at inference time for most items: just the assignment
TITLE as it appears in Canvas/PrairieLearn/a syllabus table, plus a due
date. No stated grade weight, late policy, or "optional"/"required" wording
- because real titles almost never say that.

---

You are generating a synthetic TEST set for a university-student task
urgency classifier. The classifier will only see a bare assignment TITLE
(exactly as it would appear in a Canvas/PrairieLearn course list or a
syllabus schedule table) and the number of days until it's due - no
description, no stated grade weight, no "optional"/"required" wording.

Each row: a short title, days until due, and an urgency label.

Labels: overdue, critical, high, medium, low.

Label each title by what it would REALISTICALLY be worth/mean at a
university, using real-world convention for that kind of title (e.g. a
midterm or final is usually high-stakes; a weekly reading response is
usually low-stakes; a problem set is usually medium; an admin/payment
deadline is usually high because of hard consequences) - but keep it
realistic and noisy, not mechanical:
- Include genuinely ambiguous titles where the "obvious" reading is wrong
  (e.g. a "Quiz" that's actually the final exam substitute worth 25%; a
  "Final Project" that's a small ungraded practice run)
- Vary naming conventions the way different professors/departments actually
  do: "PS3", "Problem Set 3", "HW 7", "Assignment 4: Recursion", "Lab 6
  Report", "Reading Response 4", "Discussion Post 3 (Ch. 7)", "Midterm Exam
  1", "Final Project Proposal", "Quiz 2 - Loops", "Essay Draft 2", "Group
  Milestone 2", "Tuition Payment - Winter Term", "Add/Drop Deadline",
  "Scholarship Application", "Lab Safety Certification"
- Cover course types: CS, humanities, sciences, business, plus non-course
  admin/financial/co-op deadlines
- Realistic days_until_due spread, including negative numbers (overdue)

Balance the 5 labels roughly evenly. Output exactly 50 rows as JSON Lines
(one JSON object per line, no markdown fences, no commentary before or
after):

{"title": "...", "days_until_due": <int>, "urgency": "..."}

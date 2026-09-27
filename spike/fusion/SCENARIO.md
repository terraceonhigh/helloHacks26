# SCENARIO: one fake student across every server

Seed **exactly this** into each self-hosted server, so fusion has real
cross-source joins to find. All data is fake. Every server's timezone is
`America/Vancouver`. The times below are wall-clock times there (PDT, UTC-7,
until 2026-11-01).

Student: username `fstudent`, display name **Fake Student**, email
`fstudent@example.invalid`. One fake instructor per server (`fprof`) to create
things. Passwords are random, generated into `oracles/.env` (gitignored).
Term: **2026W1** (2026 Winter Term 1, Sep–Dec 2026).

## Courses and how each server labels them

| Canonical | Moodle (shortname / fullname) | WeBWorK course id | PrairieLearn (course / instance) | Canvas fixture (course_code) |
|---|---|---|---|---|
| CPSC 121 / 2026W1 | `CPSC121-101-2026W1` / "CPSC 121 101 Models of Computation" | – | `CPSC 121` "Models of Computation" / instance `2026W1` long name "2026 Winter Term 1" | `CPSC_121_101_2026W1` |
| MATH 100 / 2026W1 | `MATH100-2026W1` / "MATH 100 Differential Calculus" | `math100_2026w1` | – | – |
| ENGL 110 / 2026W1 | `ENGL110-001-2026W1` / "ENGL 110 Approaches to Literature" | – | – | – |

`fstudent` is enrolled as a student in every one of those.

## Items per server

`<WW:HW2>` means "the deep link to WeBWorK set HW2 for fstudent on our WeBWorK
server". Moodle items put that exact URL in their description, as an
instructor would.

### WeBWorK (course `math100_2026w1`)
| id | set | open | due | notes |
|---|---|---|---|---|
| W1 | `HW1` | 2026-09-01 00:00 | 2026-09-20 23:59 | past due |
| W2 | `HW2` | 2026-09-15 00:00 | 2026-09-29 23:59 | |
| W3 | `HW9` | 2026-12-01 00:00 | 2027-01-15 23:59 | after the BC time change: trust the server's printed zone |
| W4 | `HW3` | 2026-10-10 00:00 | 2026-10-17 23:59 | not open yet |
Each set gets one problem. Any stock OPL problem will do.

### PrairieLearn (course `CPSC 121`, instance `2026W1`)
| id | assessment | type/group | 100 % credit until | notes |
|---|---|---|---|---|
| P1 | `quiz1` "Quiz 1" | Quizzes | 2026-10-02 23:59 | |
| P2 | `ps3` "Problem Set 3" | Homework | 2026-10-05 17:00 | |
| P3 | `quiz2` "Quiz 2" | Quizzes | 2026-10-16 23:59 | |
| P4 | `lab4` "Lab 4" | Labs | available from 2026-10-20 00:00, 100 % until 2026-10-27 23:59 | not open yet |

### Moodle
| id | course | activity | title | due | description / notes |
|---|---|---|---|---|---|
| M1 | MATH100 | assignment (no submission, just a pointer) | "WeBWorK HW1" | 2026-09-20 23:59 | text contains `<WW:HW1>` |
| M2 | MATH100 | assignment (pointer) | "Homework 2 (WeBWorK)" | **2026-09-29 23:00** | contains `<WW:HW2>`. The due date is deliberately 59 min off WeBWorK's (a stale copy): a conflict |
| M3 | MATH100 | course calendar event | "Midterm 1" | 2026-10-15 18:00 | only on Moodle |
| M4 | MATH100 | assignment (Moodle submission) | "Assignment 1" | 2026-10-09 23:59 | same title and due as M6 in a different course: must NOT merge |
| M5 | CPSC121 | assignment (pointer) | "PrairieLearn Quiz 1" | **none** | contains `<PL:quiz1>`. The prof forgot the due date; PL has it |
| M6 | ENGL110 | assignment (Moodle submission) | "Assignment 1" | 2026-10-09 23:59 | |
| M7 | CPSC121 | course calendar event | "Problem Set 3 due" | 2026-10-05 17:00 | no link: must merge with P2 on title + due |
| M8 | CPSC121 | assignment (Moodle submission) | "Quiz 3" | 2026-10-16 23:59 | same due as P3 "Quiz 2": must NOT merge (numbers differ) |
| M9 | ENGL110 | page resource | "Reading: Chapter 4" | none | undated material |

### Canvas (no live server in this spike: a fixture authored from Canvas's public REST API docs)
| id | course | planner item | due | notes |
|---|---|---|---|---|
| C1 | CPSC_121_101_2026W1 | assignment "Quiz 1 (PrairieLearn)" | 2026-10-02 23:59 | external-tool assignment whose description links `<PL:quiz1>` |
| C2 | CPSC_121_101_2026W1 | assignment "Tutorial 2 worksheet" | 2026-10-01 12:00 | Canvas only |

## Expected fused tracks

The fusion core must produce exactly these tracks, and no others.

| track | members | due (authority) | conflicts | evidence | action_url |
|---|---|---|---|---|---|
| MATH 100 HW1 | W1, M1 | W1 | – | link | WeBWorK HW1 |
| MATH 100 HW2 | W2, M2 | W2 (23:59) | M2 says 23:00 | link | WeBWorK HW2 |
| MATH 100 HW9 | W3 | W3 | – | – | WeBWorK HW9 (status not_open) |
| MATH 100 HW3 | W4 | W4 | – | – | WeBWorK HW3 (status not_open) |
| MATH 100 Midterm 1 | M3 | M3 | – | – | Moodle event |
| MATH 100 Assignment 1 | M4 | M4 | – | – | Moodle M4 |
| CPSC 121 Quiz 1 | P1, M5, C1 | P1 | – | link (M5→P1, C1→P1) | PL quiz1 |
| CPSC 121 Problem Set 3 | P2, M7 | P2 | – | title + due | PL ps3 |
| CPSC 121 Quiz 2 | P3 | P3 | – | – | PL quiz2 |
| CPSC 121 Quiz 3 | M8 | M8 | – | – | Moodle M8 |
| CPSC 121 Lab 4 | P4 | P4 | – | – | PL lab4 (status not_open) |
| CPSC 121 Tutorial 2 worksheet | C2 | C2 | – | – | Canvas C2 |
| ENGL 110 Assignment 1 | M6 | M6 | – | – | Moodle M6 |
| ENGL 110 Reading: Chapter 4 | M9 | – | – | – | Moodle page (status undated) |

That's 14 tracks from 19 observations. Adapters may emit extra observations
the platforms create on their own (for example a Moodle "course start" event).
If they do, list them in the oracle output. The e2e test must then either
filter them deliberately, with a comment explaining why, or count them. Never
drop them silently.

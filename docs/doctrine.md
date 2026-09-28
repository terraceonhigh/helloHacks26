# Doctrine: the Gotham analogy, and where it breaks

An internal design lens, not branding. User-facing words stay plain (pane,
row, folder), and the product never calls itself "Gotham" or "Palantir" (Jacky
cut that framing from the deck on 2026-09-27). The source is Terrace's
whiteboards: "Gotham for Students" (#1), "the human is the subagent" (#2), and
the homework kill chain (#3, `docs/whiteboards/`).

Why keep it at all: military and law-enforcement intelligence practice
is a mature discipline for fusing many unreliable sources into one decision.
Mapping it onto a student's week gives us a checklist of features. The half
that matters just as much is the list of places where the map fails.

## The mapping

| Mil/LE concept | Lauds | Status |
|---|---|---|
| ISR sensors | platforms: Canvas, PrairieLearn, WeBWorK, Workday, Moodle, … | built (adapters) |
| Collection management (tasking the sensors) | sync scheduling: which source to poll, when, how politely | partial (`lauds sync`) |
| Ontology + entity resolution | `Course` / `Item` / `Meeting` / `Textbook`; one quiz on two platforms counts once | partial (exact-match only) |
| Source reliability grading (NATO Admiralty code, A1–F6) | per-source trust; live / docs / fixture-verified grades | grades for adapters only |
| Sensor conflict | due-date drift, e.g. Canvas says X and WeBWorK says Y (`main` #23) | not surfaced yet |
| Common operating picture | the pane: `lauds today` | built |
| Intelligence preparation of the battlefield | the term view: syllabi, key dates, midterm pile-ups | not built |
| Commander's priority intelligence requirements | "what matters to you" urgency preferences | web-only on `main`, not ported |
| Deconfliction | back-to-back classes, deadline bunching, clashes | not built |
| Kill chain (find, fix, track, target, engage, assess) / OODA | whiteboard #2's student loop; whiteboard #3's table | the pane is built |
| **Target folder** | the per-item folder: Readings, Class Notes, template, submit link | next (materials fetcher) |
| Rules of engagement, weapons-release authority | academic integrity; agents prepare, only the student submits | policy (concierge yes-gate) |
| Staff vs. operator | the agent is staff; the student is the operator | by design |
| Battle damage assessment, after-action review | grades returned; post-midterm review | not built |

The rows marked "not built" are the roadmap.

## Where it breaks

1. **There's no adversary.** A kill chain assumes an opponent to defeat. Here
   the "target" is the student's own coursework, and the instructor is on the
   student's side. Nothing in Lauds should frame instructors or platforms as
   opponents to outwit.
2. **Finishing isn't learning.** A kill chain maximises engagements. Pushed
   too far, Lauds would optimise for ticked-off rows (Goodhart's law). The
   brief is the opposite: *the student does the learning.* "Assess" has to
   mean "did I understand it", not only "submitted".
3. **The subject is flipped.** Gotham's objects are other people. Lauds' only
   subject is the user: their own data, gathered with their consent, for them
   alone. That flip is the whole ethical case. Institutions do use edtech
   analytics to watch students (proctoring, "learning analytics"), so the
   analogy points straight at the thing Lauds refuses to be.
4. **One operator.** There's no chain of command and no staff hierarchy to
   report up. Anything built for approvals or reporting up a chain is out of
   scope.

## The rule

**Every concept borrowed from this table must say which break it avoids.**
For example:
- Source reliability grading is fine: it serves the student's trust in their
  own pane (breaks 1 and 3 don't apply).
- A completion streak or throughput score fails break 2 unless it also asks
  whether the student understood the work.
- Anything that could show one student's data to anyone else fails break 3,
  full stop.

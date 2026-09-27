# Lauds: 5-minute keynote script

Target 5:00 (plus or minus 30s). The script is 545 spoken words: 3.6 to 4.2 minutes of speech, plus about 45s of demo clicks and slide changes.
Slide ids match `deck.json`. Words in [brackets] are actions, not lines.

| # | Slide (id) | Starts | Length | Note |
| --- | --- | --- | --- | --- |
| 1 | Lauds (`cover`) | 0:00 | 15s |  |
| 2 | Meet Stu. (`problem`) | 0:15 | 35s |  |
| 3 | Every platform is a sensor (`solution`) | 0:50 | 30s |  |
| 4 | Gotham for students (`gotham`) | 1:20 | 35s |  |
| 5 | An OODA loop (`ooda`) | 1:55 | 35s |  |
| 6 | Product demo (switch to the live site) (`tour`) | 2:30 | 75s |  |
| 7 | How it works (`architecture`) | 3:45 | 15s |  |
| 8 | 14 platforms (`breadth`) | 4:00 | 15s |  |
| 9 | Engineering discipline (`rigor`) | 4:15 | 15s | cut first if running long |
| 10 | Built fast. Verified for real. (`proof`) | 4:30 | 15s | fold into the previous line if long |
| 11 | Already in review (`roadmap`) | 4:45 | 15s | say only the first item if long |
| 12 | Lauds. (close) (`thanks`) | 5:00 | 15s |  |

## 1. Lauds (0:00, about 15s)

Hi, I'm Terrace from Team 26. This is Lauds: sensor fusion for student life. It's the first thing you check in the morning.

## 2. Meet Stu. (0:15, about 35s)

Meet Stu. Stu has Canvas, Piazza, WeBWorK, and a couple of PrairieLearns on different domains. Workday has his timetable. The Bookstore has his textbooks. None of them talk to each other. So a quiz posted on WeBWorK never shows up on Canvas's calendar. A three-hundred-dollar textbook turns up in week two. And nothing can answer the one question Stu has every morning: what do I need to do right now?

## 3. Every platform is a sensor (0:50, about 30s)

Here's our idea. Every one of those platforms is a sensor. Each one sees its own slice of Stu's week, and nothing more. Lauds doesn't replace any of them. It reads them all, translates them into one shared model, and fuses them: duplicates merged, courses matched, everything ranked by what needs attention today.

## 4. Gotham for students (1:20, about 35s)

If that sounds familiar, it's the idea behind Palantir Gotham, which fuses many narrow intelligence feeds into one operating picture. We built Gotham for students. The sensors are across the top. Each one gets a small adapter that translates it into one shared model: courses, items and textbooks. Fusion only happens on that model. That's how CPSC underscore V 110 in Canvas and CPSC 110 in Piazza become one course. That's the product: the join, not any single connector.

## 5. An OODA loop (1:55, about 35s)

Gotham's users think in OODA loops: observe, orient, decide, act. Lauds runs that loop every morning. Observe: read every sensor. Orient: fuse it into one model, so one quiz on two platforms is one item. Decide: rank by urgency, weighted by what matters to you. Act: one click opens it where it lives, or checks it off. Most student tools stop at observe. Lauds closes the loop.

## 6. Product demo (switch to the live site) (2:30, about 75s)

Let me show you. [Switch to the browser.] This is the live site. No login: it's a made-up student in week five. [Overview] Twenty-five things due this week, five already overdue, ranked across every course. [Top assignments] The five most urgent, overdue first, and each one links straight back to the platform it came from. [Assignments tab] Here's Quiz 3. It was posted on both Canvas and PrairieLearn, and it shows up once. That's fusion. [Calendar, click Monday] Monday: a lecture, a lab and eleven deadlines from four platforms, on one screen. [Schedule tab] His timetable, straight from Workday. [Settings] And every one of these sensors is a plug-in. [Switch back to the slides.]

## 7. How it works (3:45, about 15s)

Under the hood: any sensor, one adapter, one standard database, out to the web app and a calendar feed for your phone. A new platform is one adapter file.

## 8. 14 platforms (4:00, about 15s)

Six platforms are merged today, and eight more are built and in review. Fourteen in the pipeline, and one student who never has to think about which one.

## 9. Engineering discipline (4:15, about 15s)

We held ourselves to rules you can check. Students log in themselves, so our code never sees a password. And a live test against the real Bookstore caught a bug before it shipped.

## 10. Built fast. Verified for real. (4:30, about 15s)

In numbers: six platforms, three hundred and twenty-five automated tests, three bugs caught live, and zero passwords.

## 11. Already in review (4:45, about 15s)

Next: a synced account so it follows you across devices, capture from tabs you already have open, and deadlines read straight from syllabus PDFs.

## 12. Lauds. (close) (5:00, about 15s)

Every platform a student already uses, fused into one picture, before you open any other tab. That's Lauds: the first thing you check in the morning. Thank you.

## If things go wrong

- **Live site down:** stay on the `tour` slide and talk over the two screenshots with the same demo lines.
- **Running long:** cut `rigor`, then shorten `proof` and `roadmap`.
- **Before presenting:** confirm "Samaya" on the thanks slide.

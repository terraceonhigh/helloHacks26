# Prompt for Claude Opus: UBC Student Life Integration App — Design Spec

You are a senior product designer and software architect. Design a comprehensive, buildable product spec for a web/mobile app called **"UBC Hub"** (working title) that integrates the fragmented ecosystem of platforms UBC students are forced to juggle into a single unified experience.

## Context: The Problem

UBC students currently must log into and check 10-15+ separate platforms to manage their academic life, including:

**Official systems:** Workday (registration, grades, tuition), Canvas (LMS, content, quizzes), CWL-gated services, UBC email/Microsoft 365.

**Course tools (instructor-dependent, inconsistent across courses):** Gradescope (grading), WeBWorK (homework), Piazza (Q&A/discussion), iClicker Cloud (polling), Zoom (lectures), Kaltura/Panopto (recordings), Turnitin (submissions), PrairieLearn, GitHub/JupyterHub (CS assignments), Qualtrics (surveys), ComPAIR/iPeer/peerScholar (peer assessment).

**Unofficial but essential student tools:** UBCGrades.com (grade distributions), UBCExplorer.io (prerequisite mapping/degree planning), UBCFinder.com (course/prof filtering), RateMyProfessors, UBC Community Wiki, r/UBC and faculty-specific subreddits.

**Practical/social:** Housing forums, club directories, campus maps, The Ubyssey.

The core pain point: information relevant to "what do I need to do this week for my courses" is scattered across systems with no unified login, no unified calendar, no unified notification system, and no single source of truth for deadlines.

## What I Need From You

Produce a full design document covering the following sections:

### 1. Product Vision & Scope
Define what "integration" concretely means here — is this an aggregator (pulls data via APIs/scraping and displays it), a middleware layer (auth-once, single dashboard), or a full replacement? Recommend the most realistic scope given that Canvas/Workday won't hand over deep write-access APIs to a third-party student app, and flag legal/ToS risk of scraping CWL-gated systems.

### 2. Core User Flows
Design the primary flows for a typical UBC undergrad, e.g.:
- Morning check-in: "What's due today across all my courses?"
- Week planner: unified deadline calendar pulling from Canvas assignments, Gradescope exams, WeBWorK sets, iClicker session times.
- Course-selection season: cross-referencing UBCGrades distributions + UBCExplorer prereqs + RateMyProfessors + Workday seat availability in one search.
- Notification triage: one inbox for Piazza posts, Canvas announcements, Gradescope grade releases.

### 3. System Architecture
Propose an architecture (frontend stack, backend, data layer) that accounts for:
- Which platforms expose real APIs (Canvas has a documented REST/GraphQL API; note others likely don't).
- Where you'd need screen-scraping, browser extension helpers, or user-provided ICS/RSS feeds instead of formal integration.
- Authentication strategy given CWL/SSO — evaluate OAuth-if-available vs. a secure credential vault vs. session-cookie proxying, and the tradeoffs/risks of each.
- Sync frequency, caching, and failure handling when an upstream platform changes its DOM or blocks automated access.

### 4. Data Model
Sketch a unified schema (courses, deadlines, notifications, grades, sources) that normalizes disparate platform data into one internal representation.

### 5. UI/UX Wireframe Description
Describe (in words, structured enough to hand to a designer) the key screens: unified dashboard, deadline calendar, course detail view, notification feed, and settings/integrations page where a student connects each platform.

### 6. MVP vs. Full Vision
Recommend a phased build: what should launch first (likely: Canvas API integration + manual/ICS import for everything else) versus what requires more infrastructure or partnership (deep Workday integration, official UBC endorsement).

### 7. Risks & Constraints
Explicitly address: UBC IT policy on third-party access to student systems, data privacy (FIPPA/BC privacy law since this is a public BC institution), rate-limiting/ToS violations from scraping unofficial or official sites, and sustainability of the project if a single student maintainer graduates (a known failure mode for tools like UBCGrades/UBCExplorer, which are alumni-maintained side projects).

### 8. Differentiation
Explain why this succeeds where past attempts (browser extensions, Notion templates, individual scraper scripts) have fallen short, and what would make students actually switch their daily habit to a new app.

## Output Format

Structure your response with clear headers matching the sections above. Where relevant, include a simple architecture diagram described in text/ASCII, and a sample JSON schema for the unified data model. Be concrete and technical — this will be used as the founding design doc for an actual build, not a marketing pitch.

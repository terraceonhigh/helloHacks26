# Figma

Sam has a Figma Make project exploring an alternative dashboard design
("Gather"): a sidebar (nav, course list, 4 color-theme picker), a header with
search/notifications, stat cards, a filterable assignment list, and a right
rail (calendar + insight card).

- **File:** https://www.figma.com/make/U0mqulizxvUVH1EAoOXcKi/Student-Dashboard-UI
- **What it is:** a Figma *Make* file, which means it's real React/TSX source
  (not just static design frames) — `src/App.tsx` + `src/index.css`, built
  with Tailwind CSS and Google-Fonts-hosted DM Sans.
- **Status: exploratory, not yet integrated.** This is a separate direction
  from `jacky-mockup` (the "row is a prompt" pills/table dashboard, which
  Terrace has named the direction of record for #26/#38's redesign). Building
  this out fully means resolving that overlap first — talk to Jacky/Terrace
  before investing heavily here, same as any other UI-direction change (see
  AGENTS.md's coordination protocol, rule 6).
- **Known gaps if/when this gets built out:** needs Tailwind added as a
  dependency, DM Sans self-hosted instead of the Google Fonts CDN link (the
  Comprador theme's own rule: no CDN, everything self-hosted), and every
  existing `web/` feature (Connect Canvas/PrairieLearn, the Sample-data
  toggle, Workday import, the Courses tab, done-item filtering) re-integrated
  into whatever shell wins out.

## Accessing it

The Figma MCP connector is available in this session via `/mcp` → "claude.ai
Figma" (OAuth, no password ever needed). Once connected, pull the design with
the Figma `get_design_context` tool — for a Make file specifically, use
`nodeId: "0:1"` and the file key from the URL
(`U0mqulizxvUVH1EAoOXcKi`). It returns links to the actual source files
(`src/App.tsx`, `src/index.css`, etc.), not just a screenshot.

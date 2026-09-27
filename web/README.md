# UBC Hub — web/

Next.js frontend. Two modes:

- **Sample mode** (default): fixed fake data, no backend needed. This is what's hosted on Vercel.
- **Local mode**: talks to Jacky's `hub/api.py` running on the same laptop, for real Canvas/PrairieLearn data. Canvas/PrairieLearn logins open a browser window on your machine, so this only works run locally, never hosted.

`NEXT_PUBLIC_HUB_API` decides whether local mode is *available at all* (so whether the Connect buttons/toggle even show); the in-app **"Sample data" toggle** switches between the two live, without restarting anything - matching `app.py`'s sidebar toggle.

## Import Workday courses

Unlike Canvas/PrairieLearn, Workday isn't a login - it's a `.xlsx` file the student already has ("View My Courses" export). Parsing happens **entirely in the browser** (`lib/workday.js`, a JS port of `hub/workday.py`'s rules), so it works in both modes, including the hosted Vercel site: pick a term, choose the file, and its courses merge into whatever's already showing.

## Run it locally (real data)

From the repo root:

```bash
uv run python -m hub.api          # starts the local API on http://localhost:8000
```

Then, in `web/`:

```bash
npm install                        # first time only
NEXT_PUBLIC_HUB_API=http://localhost:8000 npm run dev
```

Open http://localhost:3000, click **Connect Canvas** / **Connect PrairieLearn**, and sign in in the window that opens.

## Run it in Sample mode

```bash
npm install                        # first time only
npm run dev
```

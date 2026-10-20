# Keynote export (.pptx)

**The canonical deck is the Claude Design source one level up** (`../deck.json` + `../slides/`). Edit that first. This folder holds a PowerPoint export for presenting offline, and it can drift from the source.

- `Lauds-keynote.pptx`: 16 slides with speaker notes on every one. Slides 1-12 are the 5-minute talk. Unlike the source, the demo slide is the six-click walkthrough, and the screenshot slide (`tour`) is a backup. Slides 13-16 are the appendix: backup demo screenshots, what's real today, judge Q&A, claims to avoid.
- `build_deck.py`: regenerates it. Run from the repo root: `uv run --with python-pptx python docs/pitch/keynote/build_deck.py docs/pitch/images docs/pitch/keynote/Lauds-keynote.pptx`
- The timed script is in `../SPEAKER-NOTES.md`, the same words as the .pptx notes.

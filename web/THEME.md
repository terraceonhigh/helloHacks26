# Theme (provisional)

`web/` uses the **Comprador** theme (parchment, pomegranate accent, museum-teal links), the same palette and fonts as the Streamlit app on `main`.

It is **provisional and fluid**: expect it to change when Terrace's design lands (#14).

- All colours and fonts are CSS custom properties at the top of `app/globals.css`. Change them there, not in components.
- Light and dark follow `prefers-color-scheme`.
- Fonts are self-hosted from `public/fonts/` (OFL-1.1, see `../NOTICES.md`). Don't add Google Fonts or any other font CDN.

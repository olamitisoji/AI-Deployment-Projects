# Soji Agboola personal website

[Visit the portfolio](https://soji-agboola-portfolio.boileditem.chatgpt.site)

An original personal website combining warm editorial typography with a compact project index. Includes five case studies, a career timeline, Soji’s portrait, his roots in Nigeria and travels, selected essays from Reality Checks, and a personal film and TV watchlist. Visual references: juliuslipp.com and heyarinze.com; no reference-site source, photography, or biographical copy is reused.

## Run locally

From this folder:

```sh
python3 -m http.server 3010 --bind 127.0.0.1 --directory dist
```

Open http://127.0.0.1:3010. No installation, API keys, or database required. Check the JavaScript with `node --check dist/script.js`.

## Edit

- `dist/index.html`: homepage and project links.
- `dist/styles.css`: typography, colors, responsive layout and motion preferences.
- `dist/script.js`: filters, mobile menu and email-copy behavior.
- `dist/work/*/index.html`: case studies.
- `dist/assets/`: Soji’s supplied portrait (without photo metadata), an original monogram, and a screenshot of the synthetic Dockflow simulator.

Deploy `dist/` on a static host. This public copy omits the original hosting account identity; create your own Site when deploying a fork.

## Boundaries and verification

Echo remains a prototype with real WhatsApp voice interviewing unverified. Dockflow uses synthetic data. Company cases describe resume-derived responsibilities without unreviewed business impact figures. Software implementation used AI coding assistance.

Six pages checked for local links, asset paths, unique IDs, heading structure and image alternatives. Browser checks covered a 390px mobile layout, desktop layout, project filters, menu and Escape behavior, and case navigation. This is a presentation website, not another AI service.

# Miko Studios

**Full Service Creative Agency & Studio Space in Miami.**

![Miko Studios Logo](./miko-logo.png)

## About

Miko Studios is a full-service creative agency and studio space based in Miami. This repository contains the source code for the official website at [mikostudios.co](https://mikostudios.co).

## Tech Stack

- **HTML5** — Semantic markup
- **CSS3** — Custom properties, Grid, Flexbox, animations
- **Vanilla JavaScript** — Instagram feed integration
- **Python** — Instagram sync script (`sync_instagram.py`)
- **GitHub Pages** — Hosting & deployment

## Project Structure

```
MIKO-STUDIOS/
├── index.html              # Main page
├── css/
│   └── style.css           # Styles (custom properties, responsive)
├── img/                    # Studio images
├── data/
│   ├── instagram.json      # Cached Instagram feed data
│   └── ig_images/          # Locally cached Instagram images
├── fonts/                  # Custom typography
├── sync_instagram.py       # Instagram feed sync script
├── miko-logo.png           # Brand logo
├── favicon.ico             # Favicon (multi-resolution)
├── site.webmanifest        # PWA manifest
├── robots.txt              # Search engine directives
├── sitemap.xml             # Sitemap for SEO
└── CNAME                   # Custom domain config
```

## Instagram Sync

The Instagram feed is synced using `sync_instagram.py`, which caches posts locally to avoid exposing API tokens in the frontend.

```bash
python3 sync_instagram.py
```

## Development

This is a static site. To develop locally, simply serve the files with any HTTP server:

```bash
python3 -m http.server 8000
```

Then visit `http://localhost:8000`.

## Deployment

The site is deployed via **GitHub Pages** with a custom domain (`mikostudios.co`). Any push to the `main` branch triggers automatic deployment.

## License

All rights reserved © 2026 Miko Studios.

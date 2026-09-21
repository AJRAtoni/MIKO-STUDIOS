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

`sync_instagram.py` reads the official Instagram Login API (`v26.0`) for
`@mikostudios.co`, verifies the account, orders media by publication date and
caches nine posts. Images and reel covers are served locally. Failed downloads,
empty responses and unexpected accounts leave the existing gallery intact.

### Activation

The implementation must be connected and tested before enabling its schedule.
The old workflow was manually disabled in GitHub; editing its file is not proof
that scheduled runs are active.

1. In a Meta Business app, add the professional Instagram account as an account
   administered by the app. Request only `instagram_business_basic` for this feed.
2. Generate a **new long-lived token** from the Instagram App Dashboard, after
   authorizing the Miko account. Store it as the repository Actions secret
   `INSTAGRAM_ACCESS_TOKEN`. Do not use a one-hour OAuth token here.
3. Generate a Fernet encryption key and store it as the repository Actions secret
   `INSTAGRAM_TOKEN_KEY`. Never commit or log either secret. Retain the key in a
   secure credential store: it is required to decrypt future refreshed tokens.
4. Keep GitHub Pages configured to publish `main` / root. The workflow needs
   `contents: write` to save changes and `pages: write` to request a Pages build.
5. Enable **Sync Instagram Feed** in GitHub Actions and run it manually. Verify
   the account response, encrypted state commit and public gallery before calling
   the integration active. Confirm a subsequent scheduled run as well.

The workflow checks every 15 minutes at minutes 7, 22, 37 and 52 UTC. GitHub may
queue or delay scheduled jobs; this is not a real-time notification from Meta.
It can also be run manually. It never publishes posts to Instagram.

### Access renewal and storage

The token is stored using authenticated Fernet encryption in
`.github/instagram-token.json`. The decryption key stays in GitHub Actions
secrets. The state file contains ciphertext and renewal metadata, never a
plaintext credential. The `.github` directory is excluded from the standard
GitHub Pages/Jekyll build and is not a website asset.

The first renewal happens after 25 hours because Meta requires tokens to be at
least 24 hours old. Subsequent renewals run at most 30 days apart. Each returned
token is encrypted and committed even if the subsequent media fetch fails.
These renewal commits also provide repository activity during periods without
new posts, addressing GitHub's 60-day inactivity limit for public schedules.
Authentication revocation or a disabled workflow still requires intervention.

Once the first encrypted state is committed, `INSTAGRAM_ACCESS_TOKEN` is no
longer read; `INSTAGRAM_TOKEN_KEY` remains necessary. For deliberate reconnection,
replace the bootstrap secret with a freshly generated token and remove the old
encrypted state in a reviewed commit. Keep the key unless deliberately rotating
it. A mismatched key fails rather than silently discarding the existing state.

### Publication and verification

`publish_instagram.py` compares the public JSON and checks every image. If the
public result differs, it requests an explicit GitHub Pages build and waits for
the public gallery to match. This avoids relying on a bot commit to trigger
Pages. A failed publication is checked again on the next run, even if no new
Instagram post appeared. The last valid gallery remains available.

Only the gallery files and encrypted state are included in automated commits.
Existing site content and unrelated local files are preserved. Concurrent syncs
are serialized; pushes never force-overwrite the remote branch.

### Local verification

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 sync_instagram.py
```

Supply credentials through the environment or a secure secret manager. The
script does not read browser cookies or automatically load `.env` files. The
publication script needs `GH_TOKEN` only when a Pages build is necessary.

Sources: [Meta setup](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started),
[Meta token renewal](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login),
[GitHub Pages build API](https://docs.github.com/en/rest/pages/pages#request-a-github-pages-build).

## Development

This is a static site. To develop locally, simply serve the files with any HTTP server:

```bash
python3 -m http.server 8000
```

Then visit `http://localhost:8000`.

## Deployment

The site is deployed via **GitHub Pages** with a custom domain (`mikostudios.co`). Human pushes to `main` trigger deployment. Instagram automation requests a Pages build explicitly because commits made with `GITHUB_TOKEN` do not trigger a branch-based Pages build.

## License

All rights reserved © 2026 Miko Studios.

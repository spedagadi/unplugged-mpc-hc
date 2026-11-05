# unplugged — website

Static marketing site for unplugged. No framework, no tracking, no server. The user guide and search index are generated from `docs/settings-guide.md`; everything else is hand-authored HTML.

**Live:** https://unplugged-mpc-hc.pages.dev

## Files

- `index.html` — landing page
- `download.html` — release, hash, install notes, licences
- `hdr-tone-mapping.html` — tone-mapping explainer (search landing page)
- `decklink-capture.html` — live capture explainer (search landing page)
- `non-linear-stretch.html` — NLS explainer (search landing page)
- `calibration.html` — display target and LUT explainer (search landing page)
- `styles.css`, `site.js` — shared assets
- `assets/brand/` — wordmark, mark, icon taken from `src/unplugged-ui/assets/brand/`
- `assets/screenshots/hero-{960,1440,1920}.webp` — real Media Player capture used in the hero (generated from `Hero.png`, 3840×2160; the 12 MB source is kept local and not committed)
- `preview.html` is generated locally for artifact publishing only. It is not committed or deployed; Cloudflare would otherwise serve it as a duplicate of the homepage.
- `content-protection.html` — HDCP/DRM policy: no decryption or bypass; unencrypted, authorized sources only
- `guide.html` — generated user guide from `docs/settings-guide.md`
- `search-index.json` — generated index for the header search
- `build_guide.py` — generator for `guide.html` and `search-index.json`
- The AVSForum announcement is kept outside the deploy folder (locally at `docs/website-brief.txt`) so it is not published.
- `robots.txt`, `sitemap.xml`, `404.html`

## Deploy

Any static host works. The folder has no build step at deploy time; the generated files are committed.

### Cloudflare Pages (recommended)

1. Create a Pages project from the repository.
2. Production branch: `zion-s3-shell`.
3. Build command: none.
4. Output directory: `website`.

The site is live at https://unplugged-mpc-hc.pages.dev. Cloudflare redirects `.html` paths to clean URLs (`/guide.html` → `/guide`); canonical and sitemap URLs use the clean form.

The free plan is sufficient: 500 builds/month, 20,000 files, 25 MiB per file and 100 custom domains. A domain is the only cost.

### GitHub Pages

GitHub Pages is free for public repositories, but its terms prohibit using it as free hosting for a business, e-commerce or a commercial product site. Use Cloudflare Pages for the public product site unless you have confirmed GitHub's terms with GitHub.

### Netlify

Drag the `website` folder into Netlify, or set publish directory to `website` and build command to empty. The free plan is credit-based (300 credits/month), so check usage before relying on it.

## Regenerating the guide and search index

The guide is not hand-edited. After changing `docs/settings-guide.md`, from the `website` directory:

```powershell
python -I build_guide.py
```

This rewrites `guide.html` and `search-index.json`. The search UI is in `site.js`; it fetches the index on first open and works on every page.

## Before going live

1. **Custom domain:** when you add one, replace `https://unplugged-mpc-hc.pages.dev` in `sitemap.xml`, `robots.txt`, every canonical/`og:url`, and the guide template in `build_guide.py`. Re-run `build_guide.py`.
2. **Canonical and `og:url`** currently point at the clean `https://unplugged-mpc-hc.pages.dev` URLs. Keep them extensionless to match Cloudflare's redirects.
3. **Check the download URL and hash** on `download.html` against the GitHub release before publishing. The site currently points at `v2.1.0` and `Unplugged-setup-2.1.0.exe`.
4. **Add `og:image`** if you want a social card. It must be an absolute URL.
5. **Decide on analytics.** There is none by default. If you add any, add a privacy page and a consent path where required.

## Regenerating `preview.html`

The preview is the published artifact entry. It is the body of `index.html` with the artifact's required `<title>` and stylesheet links in front. From the repository root:

```powershell
$html = Get-Content website\index.html -Raw
$body = ($html -split '<body[^>]*>', 2)[1] -split '</body>', 2)[0]
$head = @'
<title>unplugged</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="styles.css">
'@
$out = $head + "`n" + $body
[System.IO.File]::WriteAllText((Join-Path (Get-Location) 'website\preview.html'), $out, (New-Object System.Text.UTF8Encoding($false)))
```

## Content rules

- **Competitor comparison is allowed as of the November 2026 review, but must stay factual.** Name madVR Envy and Lumagen Radiance Pro only in the comparison table and FAQ, keep prices/features date-stamped and labelled indicative, verify vendor data before launch, and include the trademark/non-affiliation line. Never assert superiority without a real A/B.
- **Testimonial:** the AVS Forum quote in the hero must be matched to an actual post/user before launch. Confirm the exact wording and that the user is comfortable being quoted anonymously.
- **Lead with the home-cinema benefit.** The landing page should read for a projector or TV owner first: home cinema, dynamic tone mapping, video processor, media player, plug in and play. Put pipeline detail, ranges and implementation notes on the subpages, below a short-version callout.
- **Every claim has a source.** Facts come from `docs/FEATURES.md`, `docs/settings-guide.md`, the GitHub release notes (2.0.0 in `docs/`, 2.1.0 on GitHub), `docs/DeckLink-Capture-Low-Latency.md`, the public release metadata and `brief.txt`. Do not add performance numbers (latency, frame rates) that have not been measured and written down.
- **No DRM circumvention framing.** Never present Blu-ray, commercial discs or streaming services as supported live sources. Never explain how to strip, disable or bypass HDCP. Do not link to tools that do. Say “unencrypted HDMI” and “content you are authorized to access.” Keep the no-circumvention statement in the footer, the FAQ and `content-protection.html`.
- **Keep the setup caveats visible.** Live HDMI requires Blackmagic's Desktop Video runtime, installed separately, and an unencrypted (non-HDCP) HDMI source. These are not optional footnotes; they prevent support threads. Also keep the 2.1.0 note that one IMAX frame can still use aspect-ratio NLS during a scope-to-IMAX transition.
- **Price and licence** are stated as free / GPL-3.0. The installer also presents end-user terms; keep the "source and licences" section on the download page accurate.
- **Trademarks.** GT7 Adapt refers to an adaptation of the Gran Turismo 7 tone-mapping operator. The footer carries the non-affiliation line; keep it if the page names GT7. Dolby and Dolby Vision are used descriptively.
- **Screenshot rights.** The hero library capture shows third-party poster artwork. It is used as an incidental product screenshot. If counsel is uncomfortable, replace it with a capture using content you own, blur the posters, or use a Video Processor capture with a test pattern. Do not add screenshots of protected commercial playback.
- **No fabricated screenshots or telemetry.** The hero pipeline lists only actual stages and defaults; the NLS diagram is labelled illustrative. Real interface captures are the best replacement: the AVSForum album is paywalled, so export them from the app (Output → Save as PNG) into `assets/screenshots/` and reference them with a caption saying which mode and source they show.
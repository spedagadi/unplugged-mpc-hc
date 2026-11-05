"""Build guide.html and search-index.json from docs/settings-guide.md.

Run from the website directory:  python -I build_guide.py
No third-party Markdown library is required.
"""

import html
import json
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
GUIDE_MD = os.path.join(os.path.dirname(ROOT), "docs", "settings-guide.md")
INDEX_HTML = os.path.join(ROOT, "index.html")
OUT_GUIDE = os.path.join(ROOT, "guide.html")
OUT_INDEX = os.path.join(ROOT, "search-index.json")

PAGES = [
    "index.html",
    "download.html",
    "hdr-tone-mapping.html",
    "decklink-capture.html",
    "non-linear-stretch.html",
    "calibration.html",
    "content-protection.html",
    "specs.html",
]


def plain(text):
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return html.unescape(text).strip()


def slugify(text, used):
    base = re.sub(r"[^a-z0-9]+", "-", plain(text).lower()).strip("-") or "section"
    slug = base
    n = 2
    while slug in used:
        slug = "%s-%d" % (base, n)
        n += 1
    used.add(slug)
    return slug


def inline(text):
    text = html.escape(text, quote=False)
    code = []

    def hold(match):
        code.append("<code>%s</code>" % match.group(1))
        return "\x00C%d\x00" % (len(code) - 1)

    text = re.sub(r"`([^`]+)`", hold, text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    for i, value in enumerate(code):
        text = text.replace("\x00C%d\x00" % i, value)
    return text


def block_start(line):
    return bool(
        line.startswith("#")
        or line.startswith("|")
        or line.startswith(">")
        or re.match(r"^\s*[-*]\s+", line)
        or re.match(r"^\s*\d+\.\s+", line)
        or line.strip() in ("---", "***", "___")
    )


def table_cells(row):
    row = row.strip().replace("\\|", "\x00PIPE\x00")
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [cell.strip().replace("\x00PIPE\x00", "|") for cell in row.split("|")]


def parse_markdown(md):
    lines = md.splitlines()
    h1 = ""
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("# "):
            h1 = line[2:].strip()
            start = i + 1
            break
    while start < len(lines) and not lines[start].strip():
        start += 1
    intro_lines = []
    while start < len(lines) and lines[start].strip() and not block_start(lines[start]):
        intro_lines.append(lines[start].strip())
        start += 1
    intro = inline(" ".join(intro_lines)) if intro_lines else ""
    lines = lines[start:]

    used = set()
    toc = []
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            text = heading.group(2).strip()
            if level == 1:
                i += 1
                continue
            anchor = slugify(text, used)
            toc.append((level, anchor, plain(text)))
            blocks.append('<h%d id="%s">%s</h%d>' % (level, anchor, inline(text), level))
            i += 1
            continue

        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            if len(rows) >= 2:
                head = table_cells(rows[0])
                body = [table_cells(row) for row in rows[2:]]
                out = ['<div class="table-wrap"><table><thead><tr>']
                out.extend("<th>%s</th>" % inline(cell) for cell in head)
                out.append("</tr></thead><tbody>")
                for row in body:
                    out.append("<tr>")
                    for cell in row:
                        out.append("<td>%s</td>" % inline(cell))
                    out.append("</tr>")
                out.append("</tbody></table></div>")
                blocks.append("".join(out))
            continue

        if line.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i][1:].lstrip())
                i += 1
            blocks.append("<blockquote><p>%s</p></blockquote>" % inline(" ".join(quote)))
            continue

        bullet = re.match(r"^\s*[-*]\s+(.*)$", line)
        numbered = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if bullet or numbered:
            ordered = bool(numbered)
            items = []
            while i < len(lines):
                current = lines[i]
                match = re.match(r"^\s*(\d+\.|[-*])\s+(.*)$", current)
                is_ordered = bool(re.match(r"^\s*\d+\.", current))
                if match and is_ordered == ordered:
                    items.append([match.group(2)])
                    i += 1
                elif items and current.strip() and not block_start(current):
                    items[-1].append(current.strip())
                    i += 1
                else:
                    break
            tag = "ol" if ordered else "ul"
            blocks.append(
                "<%s>%s</%s>"
                % (tag, "".join("<li>%s</li>" % inline(" ".join(item)) for item in items), tag)
            )
            continue

        if line.strip() in ("---", "***", "___"):
            blocks.append("<hr>")
            i += 1
            continue

        para = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not block_start(lines[i]):
            para.append(lines[i].strip())
            i += 1
        blocks.append("<p>%s</p>" % inline(" ".join(para)))

    toc_html = ['<ul>']
    for level, anchor, text in toc:
        css = "toc-h2" if level == 2 else "toc-h3"
        toc_html.append('<li class="%s"><a href="#%s">%s</a></li>' % (css, anchor, html.escape(text)))
    toc_html.append("</ul>")
    return h1, intro, "\n".join(blocks), "".join(toc_html)


def strip_tags(value):
    value = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def guide_entries(content):
    entries = []
    matches = list(re.finditer(r'<h([23]) id="([^"]+)">(.*?)</h\1>', content, re.S))
    current_h2 = "User guide"
    for i, match in enumerate(matches):
        level = int(match.group(1))
        anchor = match.group(2)
        title = strip_tags(match.group(3))
        if level == 2:
            current_h2 = title
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = strip_tags(content[match.end():end])
        if body:
            entries.append(
                {
                    "title": title,
                    "section": "User guide" if level == 2 else current_h2,
                    "url": "guide.html#%s" % anchor,
                    "text": body[:1200],
                }
            )
    return entries


def page_entries():
    entries = []
    for name in PAGES:
        path = os.path.join(ROOT, name)
        text = open(path, encoding="utf-8").read()
        title = re.search(r"<title>(.*?)</title>", text, re.S)
        title = strip_tags(title.group(1)) if title else name
        main = re.search(r"<main[^>]*>(.*?)</main>", text, re.S)
        body = strip_tags(main.group(1)) if main else ""
        entries.append(
            {
                "title": title,
                "section": "unplugged",
                "url": name,
                "text": body,
            }
        )
    return entries


def main():
    markdown = open(GUIDE_MD, encoding="utf-8").read()
    h1, intro, content, toc = parse_markdown(markdown)
    index_html = open(INDEX_HTML, encoding="utf-8").read()
    header = re.search(r'<header class="site-head">.*?</header>', index_html, re.S)
    footer = re.search(r'<footer class="site-foot">.*?</footer>', index_html, re.S)
    if not header or not footer:
        raise SystemExit("Could not find the site header/footer in index.html")

    description = (
        "The full Unplugged 2.1.0 settings guide: every control, its range, its default, "
        "and what the picture does when you move it."
    )
    guide = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>User guide — unplugged</title>
<meta name="description" content="{description}">
<link rel="canonical" href="https://www.unpluggedvideo.com/guide">
<meta property="og:url" content="https://www.unpluggedvideo.com/guide">
<meta name="theme-color" content="#000000">
<meta property="og:type" content="article">
<meta property="og:site_name" content="unplugged">
<meta property="og:title" content="Unplugged user guide">
<meta property="og:description" content="{description}">
<link rel="icon" href="assets/brand/png/unplugged-icon-32.png" sizes="32x32">
<link rel="icon" href="assets/brand/ico/unplugged.ico" sizes="any">
<link rel="apple-touch-icon" href="assets/brand/png/unplugged-icon-512.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="styles.css">
<script type="application/ld+json">
{{"@context": "https://schema.org", "@type": "TechArticle", "headline": "Unplugged user guide", "description": "{description}", "about": {{"@type": "SoftwareApplication", "name": "unplugged", "softwareVersion": "2.1.0"}}}}
</script>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>

{header}

<main id="main">

  <section class="page-hero wrap">
    <div class="crumbs"><a href="index.html">unplugged</a><span>/</span><span>User guide</span></div>
    <p class="eyebrow"><span class="dot"></span> Documentation</p>
    <h1>User guide</h1>
    <p class="lede">{intro}</p>
    <div class="actions">
      <button class="btn" type="button" data-open-search>Search the guide</button>
      <a class="btn ghost" href="download.html">Download 2.1.0</a>
    </div>
  </section>

  <section class="section wrap">
    <div class="guide-layout">
      <nav class="guide-toc" aria-label="On this page">
        <p class="guide-toc-title">On this page</p>
        {toc}
      </nav>
      <article class="guide-body prose">
        {content}
        <p class="fine" style="margin-top: 40px;">This guide ships with Unplugged 2.1.0. <a href="https://github.com/spedagadi/unplugged-mpc-hc/blob/zion-s3-shell/docs/settings-guide.md">View the Markdown source on GitHub</a>.</p>
        <p class="fine" style="margin-top: 12px;"><a href="#main">Back to top ↑</a></p>
      </article>
    </div>
  </section>

</main>

{footer}

<script src="site.js"></script>
</body>
</html>
""".format(
        description=html.escape(description),
        header=header.group(0),
        footer=footer.group(0),
        intro=intro,
        toc=toc,
        content=content,
    )
    with open(OUT_GUIDE, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(guide)
    entries = guide_entries(content) + page_entries()
    with open(OUT_INDEX, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entries, ensure_ascii=False, separators=(",", ":")))
    print("guide.html: %d bytes" % len(guide.encode("utf-8")))
    print("search-index.json: %d entries, %d bytes" % (len(entries), len(open(OUT_INDEX, "rb").read())))


if __name__ == "__main__":
    main()
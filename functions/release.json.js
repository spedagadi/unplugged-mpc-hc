/*
 * Live release data for the website.
 *
 * Cloudflare Pages serves this Function at /release.json, ahead of the
 * committed static file. The Function asks the GitHub releases API for the
 * current asset download counts, caches the answer at the edge for five
 * minutes, and returns the same shape that website/update_release.py writes.
 * Keeping the GitHub call server-side avoids the browser's 60-requests-per-
 * hour unauthenticated API limit and keeps the token out of the page.
 */

const API = "https://api.github.com/repos/spedagadi/unplugged-mpc-hc/releases?per_page=100";
const CACHE_SECONDS = 300;

function versionOf(tag) {
  return tag.indexOf("v") === 0 ? tag.slice(1) : tag;
}

function sha256Of(asset, body) {
  const digest = String((asset && asset.digest) || "");
  const digestMatch = digest.match(/sha256:([0-9a-f]{64})/i);
  if (digestMatch) return digestMatch[1].toUpperCase();
  const bodyMatch = String(body || "").match(/\b([0-9a-f]{64})\b/i);
  return bodyMatch ? bodyMatch[1].toUpperCase() : "";
}

function pickAsset(release) {
  const assets = Array.isArray(release.assets) ? release.assets.filter((item) => item && item.name) : [];
  return (
    assets.find((item) => /setup/i.test(item.name) && /\.exe$/i.test(item.name)) ||
    assets.find((item) => /\.exe$/i.test(item.name)) ||
    assets[0] ||
    {}
  );
}

function releaseRecord(release) {
  const tag = String(release.tag_name || "");
  const asset = pickAsset(release);
  const size = Number(asset.size) || 0;
  const assets = Array.isArray(release.assets) ? release.assets : [];
  return {
    tag: tag,
    version: versionOf(tag),
    name: release.name || tag,
    publishedAt: release.published_at,
    releaseUrl: release.html_url,
    downloadUrl: asset.browser_download_url || release.html_url,
    assetName: asset.name || "",
    assetSize: size,
    sizeMB: size ? Math.round(size / 1000000) : 0,
    sha256: sha256Of(asset, release.body),
    downloads: assets.reduce((sum, item) => sum + (Number(item.download_count) || 0), 0),
    prerelease: Boolean(release.prerelease),
  };
}

function payloadFrom(releases) {
  let records = releases
    .filter((release) => !release.draft && release.published_at)
    .map(releaseRecord);
  if (!records.length) throw new Error("No published releases");

  records.sort((a, b) => String(b.publishedAt).localeCompare(String(a.publishedAt)));
  const stable = records.filter((item) => !item.prerelease);
  const latest = stable[0] || records[0];
  const first = records.reduce(
    (oldest, item) => (!oldest || item.publishedAt < oldest.publishedAt ? item : oldest),
    null
  );

  return {
    generatedAt: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    source: "https://github.com/spedagadi/unplugged-mpc-hc/releases",
    latest: latest,
    releases: records,
    totals: {
      downloads: records.reduce((sum, item) => sum + item.downloads, 0),
      releases: records.length,
      firstReleaseDate: first ? first.publishedAt : null,
    },
  };
}

async function staticFallback(context) {
  if (!context.env || !context.env.ASSETS) return null;
  try {
    const asset = await context.env.ASSETS.fetch(new URL("/release.json", context.request.url));
    if (!asset.ok) return null;
    return new Response(asset.body, {
      status: 200,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    return null;
  }
}

export async function onRequestGet(context) {
  const cache = typeof caches !== "undefined" ? caches.default : null;
  const cacheKey = new Request(new URL("/__unplugged_release_cache", context.request.url), { method: "GET" });

  const cached = cache ? await cache.match(cacheKey) : null;
  if (cached) return cached;

  try {
    const headers = {
      Accept: "application/vnd.github+json",
      "User-Agent": "unplugged-website",
      "X-GitHub-Api-Version": "2022-11-28",
    };
    if (context.env && context.env.GITHUB_TOKEN) {
      headers.Authorization = "Bearer " + context.env.GITHUB_TOKEN;
    }

    const response = await fetch(API, {
      headers: headers,
      cf: { cacheTtl: CACHE_SECONDS, cacheEverything: true },
    });
    if (!response.ok) throw new Error("GitHub HTTP " + response.status);

    const releases = await response.json();
    const output = new Response(JSON.stringify(payloadFrom(releases)), {
      status: 200,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "public, max-age=" + CACHE_SECONDS,
      },
    });
    if (cache && typeof context.waitUntil === "function") {
      context.waitUntil(cache.put(cacheKey, output.clone()));
    }
    return output;
  } catch (error) {
    console.error("release.json: " + error.message);
    const fallback = await staticFallback(context);
    if (fallback) return fallback;
    return new Response(JSON.stringify({ error: "release data unavailable" }), {
      status: 502,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
      },
    });
  }
}
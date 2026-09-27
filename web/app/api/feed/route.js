import { parseIcs } from "../../../lib/ics.js";

// SSRF guard (#47): only fetch feeds from a host we trust. Add a school by
// adding its host here. FEED_TEST_HOST is for our self-hosted Canvas, whose
// domain isn't fixed/public - set via env, same as the Python oracle's
// CANVAS_BASE.
const ALLOWED_HOSTS = [/(^|\.)instructure\.com$/, /^canvas\.ubc\.ca$/];

function isAllowedHost(hostname) {
  if (ALLOWED_HOSTS.some((re) => re.test(hostname))) return true;
  return process.env.FEED_TEST_HOST === hostname;
}

// The feed URL is a secret (works like a password): never log it, in an
// error message or otherwise.
export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid JSON body" }, { status: 400 });
  }

  const feedUrl = body?.url;
  if (typeof feedUrl !== "string") {
    return Response.json({ error: "missing url" }, { status: 400 });
  }

  let parsed;
  try {
    parsed = new URL(feedUrl);
  } catch {
    return Response.json({ error: "invalid feed URL" }, { status: 400 });
  }
  if (parsed.protocol !== "https:" || !isAllowedHost(parsed.hostname)) {
    return Response.json({ error: "unsupported feed host" }, { status: 400 });
  }

  let res;
  try {
    res = await fetch(feedUrl);
  } catch {
    return Response.json({ error: "could not reach the feed" }, { status: 502 });
  }
  if (!res.ok) {
    return Response.json({ error: `feed returned ${res.status}` }, { status: 502 });
  }

  const items = parseIcs(await res.text(), "canvas", `${parsed.protocol}//${parsed.host}`);
  return Response.json({ items });
}

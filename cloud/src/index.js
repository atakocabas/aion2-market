// Shared Aion 2 market price store: users upload what their own game client
// saw, everyone downloads what the others saw.
//
//   POST /v1/register               (no key)           {} -> {key}; the app asks for its own key once
//   POST /v1/upload                 (contributor key)  {snapshots: [...], listings: [...]}
//   GET  /v1/snapshots?since=<seq>  (contributor key)  rows newer than the cursor
//   GET  /v1/listings?since=<seq>   (contributor key)
//   GET  /v1/servers                (contributor key)  server names
//   /v1/admin/...                   (ADMIN_TOKEN)      keys, server names, purge
//
// Keys are sent as "Authorization: Bearer <key>"; only their SHA-256 is stored.

const MAX_BODY = 2_000_000;
const MAX_SNAPSHOTS = 5000;
const MAX_LISTINGS = 2000;
const MAX_DOWNLOAD = 5000;
const CHUNK = 500;                      // rows per INSERT ... SELECT FROM json_each(?)
const HISTORY_SECONDS = 90 * 86400;     // oldest observation accepted
const FUTURE_SECONDS = 600;
const PRICE_MAX = 1e13;
// Self-registration: set OPEN_REGISTRATION = "false" in wrangler.toml to allow invited keys only.
const REGISTER_PER_CALLER_DAY = 3;
const REGISTER_PER_DAY = 500;
// Upload limits and bad-price protection.
const ROWS_PER_HOUR = 20000;            // snapshots + listings per key and hour (one market opening is ~600)
const OUTLIER_FACTOR = 10;              // a price over 10x or under 1/10 of the item's typical price is rejected
const REF_MIN_SAMPLES = 3;              // until an item has this many accepted prices, nothing is rejected for it
const REF_WEIGHT = 0.2;                 // how fast the typical price follows accepted prices (in log space)
const REF_UPDATE_SECONDS = 600;         // the typical price is updated at most this often per item
const REF_STALE_SECONDS = 3 * 86400;    // with no accepted price for this long it starts over (real price jumps)

export default {
  async fetch(request, env) {
    try {
      return await route(request, env);
    } catch (e) {
      if (e instanceof HttpError) return json({ error: e.message }, e.status);
      console.error(e);
      return json({ error: "internal error" }, 500);
    }
  },
};

class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

async function sha256(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
}

function bearer(request) {
  const h = request.headers.get("Authorization") || "";
  return h.startsWith("Bearer ") ? h.slice(7).trim() : "";
}

async function contributor(request, env) {
  const key = bearer(request);
  if (!key) throw new HttpError(401, "missing key");
  const row = await env.DB.prepare("SELECT id, name, active, window_start, window_rows FROM contributors WHERE key_hash = ?")
    .bind(await sha256(key)).first();
  if (!row || !row.active) throw new HttpError(401, "invalid key");
  await env.DB.prepare("UPDATE contributors SET last_seen_ts = ? WHERE id = ?").bind(Date.now() / 1000, row.id).run();
  return row;
}

async function requireAdmin(request, env) {
  const token = bearer(request);
  if (!env.ADMIN_TOKEN || env.ADMIN_TOKEN.length < 16) throw new HttpError(503, "ADMIN_TOKEN is not configured");
  // Compare digests so the check takes the same time whatever the input.
  const [a, b] = await Promise.all([sha256(token), sha256(env.ADMIN_TOKEN)]);
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  if (diff !== 0) throw new HttpError(401, "invalid admin token");
}

async function body(request) {
  const len = +(request.headers.get("Content-Length") || 0);
  if (len > MAX_BODY) throw new HttpError(413, "body too large");
  const text = await request.text();
  if (text.length > MAX_BODY) throw new HttpError(413, "body too large");
  try { return JSON.parse(text || "{}"); } catch { throw new HttpError(400, "invalid json"); }
}

const isKey = v => typeof v === "string" && /^\d{6,12}$/.test(v);
const isServer = v => Number.isInteger(v) && v > 0 && v < 1e9;
const isPrice = v => typeof v === "number" && Number.isFinite(v) && v > 0 && v < PRICE_MAX;
const isCount = v => Number.isInteger(v) && v >= 0 && v < 1e7;
const isText = (v, max) => v == null || (typeof v === "string" && v.length <= max);
const optInt = v => (v == null ? null : Number.isInteger(v) ? v : NaN);

function tsOk(ts, now) {
  return typeof ts === "number" && Number.isFinite(ts) && ts <= now + FUTURE_SECONDS && ts >= now - HISTORY_SECONDS;
}

// [server_id, item_key, ts, min_unit_price, sale_count]
function cleanSnapshots(rows, now) {
  if (!Array.isArray(rows)) return [[], 0];
  if (rows.length > MAX_SNAPSHOTS) throw new HttpError(413, `at most ${MAX_SNAPSHOTS} snapshots per request`);
  const ok = rows.filter(r => Array.isArray(r) && r.length === 5 && isServer(r[0]) && isKey(r[1]) &&
    tsOk(r[2], now) && isPrice(r[3]) && isCount(r[4]));
  return [ok, rows.length - ok.length];
}

// [server_id, item_key, ts, sale_id, quantity, sale_price, unit_price, effective_from, effective_to, grade_id, category_id]
function cleanListings(rows, now) {
  if (!Array.isArray(rows)) return [[], 0];
  if (rows.length > MAX_LISTINGS) throw new HttpError(413, `at most ${MAX_LISTINGS} listings per request`);
  const ok = rows.filter(r => Array.isArray(r) && r.length === 11 && isServer(r[0]) && isKey(r[1]) &&
    tsOk(r[2], now) && typeof r[3] === "string" && /^[0-9A-Fa-f-]{8,64}$/.test(r[3]) &&
    Number.isInteger(r[4]) && r[4] > 0 && r[4] < 1e6 && isPrice(r[5]) && isPrice(r[6]) &&
    isText(r[7], 40) && isText(r[8], 40) && !Number.isNaN(optInt(r[9])) && !Number.isNaN(optInt(r[10])));
  return [ok, rows.length - ok.length];
}

async function insertChunks(env, sql, rows, extra) {
  let inserted = 0;
  for (let i = 0; i < rows.length; i += CHUNK) {
    const chunk = rows.slice(i, i + CHUNK);
    const res = await env.DB.prepare(sql).bind(JSON.stringify(chunk), ...extra).run();
    inserted += res.meta.changes || 0;
  }
  return inserted;
}

function newKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  return "a2m_" + [...bytes].map(b => b.toString(16).padStart(2, "0")).join("");
}

async function register(request, env) {
  if (String(env.OPEN_REGISTRATION ?? "true") === "false") throw new HttpError(403, "registration is closed");
  if (!env.ADMIN_TOKEN || env.ADMIN_TOKEN.length < 16) throw new HttpError(503, "ADMIN_TOKEN is not configured");
  const now = Date.now() / 1000;
  const day = new Date().toISOString().slice(0, 10);
  const caller = await sha256(`${request.headers.get("CF-Connecting-IP") || "local"}|${env.ADMIN_TOKEN}`);
  await env.DB.prepare("DELETE FROM registrations WHERE day < ?").bind(day).run();
  const [mine, all] = await env.DB.batch([
    env.DB.prepare("SELECT count FROM registrations WHERE day = ? AND caller = ?").bind(day, caller),
    env.DB.prepare("SELECT COALESCE(SUM(count), 0) AS n FROM registrations WHERE day = ?").bind(day),
  ]);
  if ((mine.results[0]?.count || 0) >= REGISTER_PER_CALLER_DAY || all.results[0].n >= REGISTER_PER_DAY) {
    throw new HttpError(429, "too many registrations today");
  }
  const key = newKey();
  const [res] = await env.DB.batch([
    env.DB.prepare("INSERT INTO contributors (name, key_hash, created_ts, auto) VALUES ('app', ?, ?, 1)")
      .bind(await sha256(key), now),
    env.DB.prepare(`INSERT INTO registrations VALUES (?, ?, 1)
                    ON CONFLICT(day, caller) DO UPDATE SET count = count + 1`).bind(day, caller),
  ]);
  return json({ id: res.meta.last_row_id, key });            // the only time the key is shown
}

// Rows per key and hour; throws 429 when this upload would go over.
async function takeQuota(env, who, rows, now) {
  const fresh = now - who.window_start >= 3600;
  const used = fresh ? 0 : who.window_rows;
  if (used + rows > ROWS_PER_HOUR) throw new HttpError(429, `at most ${ROWS_PER_HOUR} rows per hour`);
  await env.DB.prepare("UPDATE contributors SET window_start = ?, window_rows = ? WHERE id = ?")
    .bind(fresh ? now : who.window_start, used + rows, who.id).run();
}

// Drops snapshots far from the item's typical price and moves the typical price toward the rest.
async function screenSnapshots(env, snaps, now) {
  if (!snaps.length) return [snaps, 0];
  const items = [...new Map(snaps.map(r => [`${r[0]}|${r[1]}`, [r[0], r[1]]])).values()];
  const refs = new Map();
  for (let i = 0; i < items.length; i += CHUNK) {
    const { results } = await env.DB.prepare(
      `SELECT r.server_id, r.item_key, r.ref_price, r.samples, r.updated_ts FROM item_ref r
       JOIN json_each(?1) j ON r.server_id = json_extract(j.value, '$[0]') AND r.item_key = json_extract(j.value, '$[1]')`)
      .bind(JSON.stringify(items.slice(i, i + CHUNK))).all();
    for (const r of results) if (now - r.updated_ts < REF_STALE_SECONDS) refs.set(`${r.server_id}|${r.item_key}`, r);
  }
  const ok = [], latest = new Map();
  for (const r of snaps) {
    const id = `${r[0]}|${r[1]}`, ref = refs.get(id);
    if (ref && ref.samples >= REF_MIN_SAMPLES &&
        (r[3] > ref.ref_price * OUTLIER_FACTOR || r[3] < ref.ref_price / OUTLIER_FACTOR)) continue;
    ok.push(r);
    if (!latest.has(id) || latest.get(id)[2] < r[2]) latest.set(id, r);
  }
  const updates = [];
  for (const [id, r] of latest) {
    const ref = refs.get(id);
    if (!ref) updates.push([r[0], r[1], r[3], 1]);
    else if (now - ref.updated_ts >= REF_UPDATE_SECONDS) {
      const price = Math.exp((1 - REF_WEIGHT) * Math.log(ref.ref_price) + REF_WEIGHT * Math.log(r[3]));
      updates.push([r[0], r[1], price, ref.samples + 1]);
    }
  }
  await insertChunks(env,
    `INSERT INTO item_ref (server_id, item_key, ref_price, samples, updated_ts)
     SELECT json_extract(value, '$[0]'), json_extract(value, '$[1]'), json_extract(value, '$[2]'), json_extract(value, '$[3]'), ?2
     FROM json_each(?1) WHERE true
     ON CONFLICT(server_id, item_key) DO UPDATE SET
       ref_price = excluded.ref_price, samples = excluded.samples, updated_ts = excluded.updated_ts`, updates, [now]);
  return [ok, snaps.length - ok.length];
}

async function upload(request, env) {
  const who = await contributor(request, env);
  const data = await body(request);
  const now = Date.now() / 1000;
  const [cleanSnaps, badSnaps] = cleanSnapshots(data.snapshots, now);
  const [lists, badLists] = cleanListings(data.listings, now);
  await takeQuota(env, who, cleanSnaps.length + lists.length, now);
  const [snaps, outliers] = await screenSnapshots(env, cleanSnaps, now);
  const snapInserted = await insertChunks(env,
    `INSERT OR IGNORE INTO snapshots (server_id, item_key, ts, min_unit_price, sale_count, contributor_id, received_ts)
     SELECT json_extract(value, '$[0]'), json_extract(value, '$[1]'), json_extract(value, '$[2]'),
            json_extract(value, '$[3]'), json_extract(value, '$[4]'), ?2, ?3
     FROM json_each(?1)`, snaps, [who.id, now]);
  const listInserted = await insertChunks(env,
    `INSERT OR IGNORE INTO listings (server_id, item_key, ts, sale_id, quantity, sale_price, unit_price,
                                     effective_from, effective_to, grade_id, category_id, contributor_id, received_ts)
     SELECT json_extract(value, '$[0]'), json_extract(value, '$[1]'), json_extract(value, '$[2]'),
            json_extract(value, '$[3]'), json_extract(value, '$[4]'), json_extract(value, '$[5]'),
            json_extract(value, '$[6]'), json_extract(value, '$[7]'), json_extract(value, '$[8]'),
            json_extract(value, '$[9]'), json_extract(value, '$[10]'), ?2, ?3
     FROM json_each(?1)`, lists, [who.id, now]);
  return json({ snapshots: { inserted: snapInserted, rejected: badSnaps, outliers },
                listings: { inserted: listInserted, rejected: badLists } });
}

async function download(request, env, table) {
  await contributor(request, env);
  const url = new URL(request.url);
  const since = Math.max(0, parseInt(url.searchParams.get("since") || "0", 10) || 0);
  const limit = Math.min(MAX_DOWNLOAD, Math.max(1, parseInt(url.searchParams.get("limit") || `${MAX_DOWNLOAD}`, 10) || MAX_DOWNLOAD));
  const cols = table === "snapshots"
    ? "seq, server_id, item_key, ts, min_unit_price, sale_count"
    : "seq, server_id, item_key, ts, sale_id, quantity, sale_price, unit_price, effective_from, effective_to, grade_id, category_id";
  const { results } = await env.DB.prepare(`SELECT ${cols} FROM ${table} WHERE seq > ? ORDER BY seq LIMIT ?`)
    .bind(since, limit + 1).raw().then(rows => ({ results: rows }));
  const more = results.length > limit;
  const rows = more ? results.slice(0, limit) : results;
  return json({ rows, next: rows.length ? rows[rows.length - 1][0] : since, more });
}

async function admin(request, env, path) {
  await requireAdmin(request, env);
  const now = Date.now() / 1000;
  if (path === "/v1/admin/keys" && request.method === "GET") {
    const { results } = await env.DB.prepare(
      `SELECT c.id, c.name, c.active, c.auto, c.created_ts, c.last_seen_ts,
              (SELECT COUNT(*) FROM snapshots s WHERE s.contributor_id = c.id) AS snapshots
       FROM contributors c ORDER BY c.id`).all();
    return json({ contributors: results });
  }
  const data = await body(request);
  if (path === "/v1/admin/keys" && request.method === "POST") {
    const name = String(data.name || "").trim().slice(0, 60);
    if (!name) throw new HttpError(400, "name required");
    const key = newKey();
    const res = await env.DB.prepare("INSERT INTO contributors (name, key_hash, created_ts) VALUES (?, ?, ?)")
      .bind(name, await sha256(key), now).run();
    return json({ id: res.meta.last_row_id, name, key });     // the only time the key is shown
  }
  if (path === "/v1/admin/keys/revoke" && request.method === "POST") {
    const res = await env.DB.prepare("UPDATE contributors SET active = 0 WHERE id = ?").bind(+data.id).run();
    return json({ revoked: res.meta.changes });
  }
  if (path === "/v1/admin/purge" && request.method === "POST") {
    const id = +data.contributor_id;
    const [a, b] = await env.DB.batch([
      env.DB.prepare("DELETE FROM snapshots WHERE contributor_id = ?").bind(id),
      env.DB.prepare("DELETE FROM listings WHERE contributor_id = ?").bind(id),
    ]);
    return json({ snapshots: a.meta.changes, listings: b.meta.changes });
  }
  if (path === "/v1/admin/servers" && request.method === "POST") {
    if (!isServer(data.server_id) || !String(data.name || "").trim()) throw new HttpError(400, "server_id and name required");
    await env.DB.prepare("INSERT INTO servers VALUES (?, ?) ON CONFLICT(server_id) DO UPDATE SET name = excluded.name")
      .bind(data.server_id, String(data.name).trim().slice(0, 40)).run();
    return json({ ok: true });
  }
  throw new HttpError(404, "not found");
}

async function route(request, env) {
  const path = new URL(request.url).pathname;
  if (path === "/v1/register" && request.method === "POST") return register(request, env);
  if (path === "/v1/upload" && request.method === "POST") return upload(request, env);
  if (path === "/v1/snapshots" && request.method === "GET") return download(request, env, "snapshots");
  if (path === "/v1/listings" && request.method === "GET") return download(request, env, "listings");
  if (path === "/v1/servers" && request.method === "GET") {
    await contributor(request, env);
    const { results } = await env.DB.prepare("SELECT server_id, name FROM servers").all();
    return json({ servers: results });
  }
  if (path.startsWith("/v1/admin/")) return admin(request, env, path);
  if (path === "/" || path === "/v1/health") return json({ ok: true, service: "aion2-market" });
  throw new HttpError(404, "not found");
}

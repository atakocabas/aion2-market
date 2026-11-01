import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { start, ADMIN_TOKEN, now } from "./harness.mjs";

let w;
before(async () => { w = await start(); });
after(async () => { await w?.server.close(); });

const admin = (path, body) => w.api(path, { key: ADMIN_TOKEN, body });
async function newKey(name = "test") {
  const r = await admin("/v1/admin/keys", { name });
  assert.equal(r.status, 200);
  return r.body;                                            // {id, name, key}
}
const upload = (key, body) => w.api("/v1/upload", { key, body });
const contributor = id => w.db.prepare("SELECT * FROM contributors WHERE id = ?").bind(id).first();
const ref = (server, item) =>
  w.db.prepare("SELECT * FROM item_ref WHERE server_id = ? AND item_key = ?").bind(server, item).first();
// Every test uses its own server id, so item_ref rows don't leak between tests.
let nextServer = 1000;
const server = () => nextServer++;

const snap = (srv, item, ts, price, count = 1) => [srv, item, ts, price, count];
const listing = (srv, item, ts, saleId, unit = 100) =>
  [srv, item, ts, saleId, 2, unit * 2, unit, "2026-01-01T00:00:00", "2026-01-08T00:00:00", 3, 7];
const item = (key, name) => [key, name, "rare", "Rare", "weapon", "sword", "https://example.com/i.png"];

test("health", async () => {
  for (const path of ["/", "/v1/health"]) {
    const r = await w.api(path);
    assert.equal(r.status, 200);
    assert.deepEqual(r.body, { ok: true, service: "aion2-market" });
  }
  assert.equal((await w.api("/v1/nope")).status, 404);
});

test("register gives an a2m_ key and allows 3 per caller and day", async () => {
  const headers = { "CF-Connecting-IP": "203.0.113.7" };
  const keys = [];
  for (let i = 0; i < 3; i++) {
    const r = await w.api("/v1/register", { body: {}, headers });
    assert.equal(r.status, 200);
    assert.match(r.body.key, /^a2m_[0-9a-f]{48}$/);
    keys.push(r.body);
  }
  const r = await w.api("/v1/register", { body: {}, headers });
  assert.equal(r.status, 429);
  assert.equal((await w.api("/v1/register", { body: {}, headers: { "CF-Connecting-IP": "203.0.113.8" } })).status, 200);
  const row = await contributor(keys[0].id);
  assert.equal(row.auto, 1);
  assert.notEqual(row.key_hash, keys[0].key);               // only the hash is stored
  assert.equal((await w.api("/v1/servers", { key: keys[0].key })).status, 200);
});

test("missing or invalid key gives 401", async () => {
  for (const path of ["/v1/snapshots", "/v1/listings", "/v1/items", "/v1/servers"]) {
    assert.equal((await w.api(path)).status, 401);
    assert.equal((await w.api(path, { key: "a2m_nope" })).status, 401);
  }
  assert.equal((await upload(undefined, {})).status, 401);
  assert.equal((await upload("a2m_nope", {})).status, 401);
  assert.equal((await w.api("/v1/servers", { headers: { Authorization: "Basic abc" } })).status, 401);
});

test("upload counts bad rows as rejected", async () => {
  const { key } = await newKey();
  const s = server(), t = now() - 60;
  const r = await upload(key, {
    snapshots: [
      snap(s, "100000001", t, 100),
      snap(s, "12345", t, 100),                             // item key too short
      snap(s, "100000002", t, 0),                           // price not > 0
      snap(s, "100000003", now() - 91 * 86400, 100),        // too old
      snap(s, "100000004", now() + 3600, 100),              // in the future
      snap(0, "100000005", t, 100),                         // bad server
      [s, "100000006", t, 100],                             // too short
      "junk",
    ],
    listings: [listing(s, "100000001", t, "aaaaaaaa-1111"), listing(s, "100000001", t, "not hex!"),
               [...listing(s, "100000001", t, "bbbbbbbb-2222").slice(0, 10), 1.5]],
    items: [item("100000001", "Sword"), item("100000002", "  "), [...item("100000003", "Bow").slice(0, 6), "http://x"]],
  });
  assert.equal(r.status, 200);
  assert.deepEqual(r.body, { snapshots: { inserted: 1, rejected: 7, outliers: 0 },
                             listings: { inserted: 1, rejected: 2 }, items: { inserted: 1, rejected: 2 } });
  assert.equal((await upload(key, "{oops")).status, 400);
  assert.equal((await upload(key, { snapshots: "x" })).body.snapshots.inserted, 0);
});

test("upload body and row limits give 413", async () => {
  const { key } = await newKey();
  const s = server(), t = now() - 60;
  assert.equal((await upload(key, "x".repeat(2_000_001))).status, 413);
  const many = n => Array.from({ length: n }, (_, i) => i);
  assert.equal((await upload(key, { snapshots: many(5001).map(i => snap(s, String(100000000 + i), t, 1)) })).status, 413);
  assert.equal((await upload(key, { listings: many(2001) })).status, 413);
  assert.equal((await upload(key, { items: many(2001) })).status, 413);
  // Exactly at the limit is fine (and goes through more than one insert chunk).
  const r = await upload(key, { snapshots: many(5000).map(i => snap(s, String(100000000 + i), t, 1)) });
  assert.equal(r.status, 200);
  assert.equal(r.body.snapshots.inserted, 5000);
});

test("duplicates are ignored", async () => {
  const { id, key } = await newKey();
  const s = server(), t = now() - 120;
  const body = { snapshots: [snap(s, "200000001", t, 50), snap(s, "200000002", t, 60)],
                 listings: [listing(s, "200000001", t, "cccccccc-0001")], items: [item("200000001", "First")] };
  const a = await upload(key, body);
  assert.deepEqual([a.body.snapshots.inserted, a.body.listings.inserted, a.body.items.inserted], [2, 1, 1]);
  body.snapshots.push(snap(s, "200000001", t + 1, 55));
  body.items = [item("200000001", "Second")];
  const b = await upload(key, body);
  assert.deepEqual([b.body.snapshots.inserted, b.body.listings.inserted, b.body.items.inserted], [1, 0, 0]);
  const info = await w.db.prepare("SELECT name FROM item_info WHERE item_key = '200000001'").first();
  assert.equal(info.name, "First");                         // the first upload per item is kept
  assert.equal((await contributor(id)).snapshots, 3);
});

test("downloads page with since, next and more", async () => {
  const { key } = await newKey();
  const s = server(), t = now() - 300;
  const top = await w.db.prepare("SELECT COALESCE(MAX(seq), 0) AS n FROM snapshots").first();
  const items = ["300000001", "300000002", "300000003", "300000004", "300000005"];
  await upload(key, { snapshots: items.map((k, i) => snap(s, k, t + i, 10 + i, i)),
                      listings: [listing(s, items[0], t, "dddddddd-0001")], items: [item(items[0], "Paged")] });
  const get = (path, since, limit) => w.api(`${path}?since=${since}&limit=${limit}`, { key });

  let since = top.n, seen = [];
  for (let page = 0; page < 3; page++) {
    const r = await get("/v1/snapshots", since, 2);
    assert.equal(r.status, 200);
    seen.push(...r.body.rows);
    assert.equal(r.body.more, page < 2);
    assert.equal(r.body.next, r.body.rows.at(-1)[0]);
    since = r.body.next;
  }
  assert.deepEqual(seen.map(r => r[2]), items);
  assert.deepEqual(seen[1], [seen[1][0], s, "300000002", t + 1, 11, 1]);
  const end = await get("/v1/snapshots", since, 2);
  assert.deepEqual(end.body, { rows: [], next: since, more: false });

  const l = await w.api("/v1/listings?since=0", { key });
  const row = l.body.rows.find(r => r[4] === "dddddddd-0001");
  assert.deepEqual(row.slice(1), [s, items[0], t, "dddddddd-0001", 2, 200, 100, "2026-01-01T00:00:00", "2026-01-08T00:00:00", 3, 7]);
  const i = await w.api("/v1/items?since=0", { key });
  assert.deepEqual(i.body.rows.find(r => r[1] === items[0]).slice(1),
                   [items[0], "Paged", "rare", "Rare", "weapon", "sword", "https://example.com/i.png"]);
  // Bad cursors fall back to the defaults.
  assert.equal((await w.api("/v1/snapshots?since=-5&limit=abc", { key })).status, 200);
});

test("one key alone never makes an item reject prices", async () => {
  const a = await newKey("a"), b = await newKey("b");
  const s = server(), it = "400000001", t = now() - 60;
  await upload(a.key, { snapshots: [snap(s, it, t, 100)] });
  assert.deepEqual(await ref(s, it).then(r => [r.samples, r.first_contributor, r.multi]), [1, a.id, 0]);
  // Pretend key a alone pushed it to many samples: its typical price still blocks nobody.
  await w.db.prepare("UPDATE item_ref SET samples = 10 WHERE server_id = ? AND item_key = ?").bind(s, it).run();
  const r1 = await upload(a.key, { snapshots: [snap(s, it, t + 1, 5000)] });
  assert.deepEqual(r1.body.snapshots, { inserted: 1, rejected: 0, outliers: 0 });
  const r2 = await upload(b.key, { snapshots: [snap(s, it, t + 2, 5000)] });
  assert.deepEqual(r2.body.snapshots, { inserted: 1, rejected: 0, outliers: 0 });
  // Now a second key has sent prices: far ones are rejected, from either key.
  const r3 = await upload(a.key, { snapshots: [snap(s, it, t + 3, 1001), snap(s, it, t + 4, 9), snap(s, it, t + 5, 150)] });
  assert.deepEqual(r3.body.snapshots, { inserted: 1, rejected: 0, outliers: 2 });
  assert.equal((await ref(s, it)).multi, 1);
});

test("an item rejects outliers after 3 samples and a second key", async () => {
  const a = await newKey("a"), b = await newKey("b");
  const s = server(), it = "500000001", t = now() - 60;
  const age = () => w.db.prepare("UPDATE item_ref SET updated_ts = updated_ts - 601 WHERE server_id = ?").bind(s).run();
  await upload(a.key, { snapshots: [snap(s, it, t, 100)] });
  await upload(a.key, { snapshots: [snap(s, it, t + 1, 100)] });   // within 600 s: no new sample
  assert.equal((await ref(s, it)).samples, 1);
  await age();
  await upload(a.key, { snapshots: [snap(s, it, t + 2, 100)] });
  await age();
  await upload(b.key, { snapshots: [snap(s, it, t + 3, 100)] });
  const r = await ref(s, it);
  assert.deepEqual([r.samples, r.first_contributor, r.multi], [3, a.id, 1]);
  assert.ok(Math.abs(r.ref_price - 100) < 1e-6);
  const out = await upload(a.key, { snapshots: [snap(s, it, t + 4, 1001), snap(s, it, t + 5, 999)] });
  assert.deepEqual(out.body.snapshots, { inserted: 1, rejected: 0, outliers: 1 });
  // A typical price nobody confirmed for 3 days starts over.
  await w.db.prepare("UPDATE item_ref SET updated_ts = ? WHERE server_id = ?").bind(now() - 3 * 86400 - 1, s).run();
  const fresh = await upload(b.key, { snapshots: [snap(s, it, t + 6, 5000)] });
  assert.equal(fresh.body.snapshots.outliers, 0);
  assert.deepEqual(await ref(s, it).then(r => [r.samples, r.ref_price, r.multi]), [1, 5000, 0]);
});

test("hourly row quota gives 429", async () => {
  const { id, key } = await newKey();
  const s = server(), t = now() - 60;
  await upload(key, { snapshots: [snap(s, "600000001", t, 1), snap(s, "600000002", t, 1)] });
  let c = await contributor(id);
  assert.equal(c.window_rows, 2);
  await w.db.prepare("UPDATE contributors SET window_rows = 19999 WHERE id = ?").bind(id).run();
  const over = await upload(key, { snapshots: [snap(s, "600000003", t, 1), snap(s, "600000004", t, 1)] });
  assert.equal(over.status, 429);
  assert.equal((await upload(key, { snapshots: [snap(s, "600000005", t, 1)] })).status, 200);
  // A new hour starts the count over.
  await w.db.prepare("UPDATE contributors SET window_start = window_start - 3600 WHERE id = ?").bind(id).run();
  assert.equal((await upload(key, { snapshots: [snap(s, "600000006", t, 1), snap(s, "600000007", t, 1)] })).status, 200);
  c = await contributor(id);
  assert.equal(c.window_rows, 2);
});

test("admin needs the token", async () => {
  for (const key of [undefined, "wrong-token-but-long-enough", ADMIN_TOKEN + "x"]) {
    assert.equal((await w.api("/v1/admin/keys", { key })).status, 401);
    assert.equal((await w.api("/v1/admin/keys", { key, body: { name: "x" } })).status, 401);
  }
  assert.equal((await admin("/v1/admin/keys", { name: " " })).status, 400);
  assert.equal((await admin("/v1/admin/unknown", {})).status, 404);
});

test("admin keys, counter, revoke and purge", async () => {
  const k = await newKey("Ali");
  assert.match(k.key, /^a2m_[0-9a-f]{48}$/);
  const s = server(), t = now() - 60;
  const list = async () => (await w.api("/v1/admin/keys", { key: ADMIN_TOKEN })).body.contributors.find(c => c.id === k.id);
  assert.deepEqual(await list().then(c => [c.name, c.active, c.auto, c.snapshots]), ["Ali", 1, 0, 0]);
  await upload(k.key, { snapshots: [snap(s, "700000001", t, 5), snap(s, "700000002", t, 5)],
                        listings: [listing(s, "700000001", t, "eeeeeeee-0001")], items: [item("700000001", "Purged")] });
  await upload(k.key, { snapshots: [snap(s, "700000001", t, 5), snap(s, "700000003", t, 5)] });
  assert.equal((await list()).snapshots, 3);                // duplicates don't count

  const purge = await admin("/v1/admin/purge", { contributor_id: k.id });
  assert.deepEqual(purge.body, { snapshots: 3, listings: 1, items: 1 });
  assert.equal((await list()).snapshots, 0);
  const left = await w.db.prepare(
    `SELECT (SELECT COUNT(*) FROM snapshots WHERE contributor_id = ?1) + (SELECT COUNT(*) FROM listings WHERE contributor_id = ?1)
          + (SELECT COUNT(*) FROM item_info WHERE contributor_id = ?1) AS n`).bind(k.id).first();
  assert.equal(left.n, 0);

  assert.deepEqual((await admin("/v1/admin/keys/revoke", { id: k.id })).body, { revoked: 1 });
  assert.equal((await list()).active, 0);
  assert.equal((await w.api("/v1/servers", { key: k.key })).status, 401);
  assert.equal((await upload(k.key, {})).status, 401);
});

test("server names show up in /v1/servers", async () => {
  const { key } = await newKey();
  assert.equal((await admin("/v1/admin/servers", { server_id: 12306, name: "Old" })).status, 200);
  assert.equal((await admin("/v1/admin/servers", { server_id: 12306, name: " Siel " })).status, 200);
  assert.equal((await admin("/v1/admin/servers", { server_id: "12306", name: "x" })).status, 400);
  assert.equal((await admin("/v1/admin/servers", { server_id: 12307 })).status, 400);
  const r = await w.api("/v1/servers", { key });
  assert.deepEqual(r.body.servers.filter(x => x.server_id === 12306), [{ server_id: 12306, name: "Siel" }]);
});

test("last_seen_ts is written at most every 10 minutes", async () => {
  const { id, key } = await newKey();
  assert.equal((await contributor(id)).last_seen_ts, null);
  await w.api("/v1/servers", { key });
  const first = (await contributor(id)).last_seen_ts;
  assert.ok(first > now() - 60);
  const old = first - 300;                                  // 5 minutes ago: kept
  await w.db.prepare("UPDATE contributors SET last_seen_ts = ? WHERE id = ?").bind(old, id).run();
  await w.api("/v1/servers", { key });
  assert.equal((await contributor(id)).last_seen_ts, old);
  await w.db.prepare("UPDATE contributors SET last_seen_ts = ? WHERE id = ?").bind(first - 601, id).run();
  await w.api("/v1/servers", { key });
  assert.ok((await contributor(id)).last_seen_ts >= first);
});

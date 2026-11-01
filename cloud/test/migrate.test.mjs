// migrate-002.sql on a database made with the schema before it (test/schema-d3ba669.sql, from commit d3ba669).
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { start, exec, sql, ADMIN_TOKEN, now } from "./harness.mjs";

let w;
before(async () => { w = await start(sql("test/schema-d3ba669.sql")); });
after(async () => { await w?.server.close(); });

const columns = async table => (await w.db.prepare(`PRAGMA table_info(${table})`).all()).results.map(c => c.name);

test("migrate-002 backfills the snapshot counter and marks known items multi", async () => {
  assert.ok(!(await columns("contributors")).includes("snapshots"));
  const t = now() - 60;
  await exec(w.db, `
    INSERT INTO contributors (id, name, key_hash, created_ts) VALUES (1, 'a', 'h1', ${t}), (2, 'b', 'h2', ${t});
    INSERT INTO snapshots (server_id, item_key, ts, min_unit_price, sale_count, contributor_id, received_ts) VALUES
      (1, '100000001', ${t}, 10, 1, 1, ${t}), (1, '100000002', ${t}, 10, 1, 1, ${t}), (1, '100000003', ${t}, 10, 1, 1, ${t});
    INSERT INTO item_ref (server_id, item_key, ref_price, samples, updated_ts) VALUES
      (1, '100000001', 10, 3, ${t}), (1, '100000002', 10, 7, ${t}), (1, '100000003', 10, 2, ${t});`);
  await exec(w.db, sql("migrate-002.sql"));

  const c = (await w.db.prepare("SELECT id, snapshots FROM contributors ORDER BY id").all()).results;
  assert.deepEqual(c, [{ id: 1, snapshots: 3 }, { id: 2, snapshots: 0 }]);
  const r = (await w.db.prepare("SELECT item_key, multi, first_contributor FROM item_ref ORDER BY item_key").all()).results;
  assert.deepEqual(r, [{ item_key: "100000001", multi: 1, first_contributor: null },
                       { item_key: "100000002", multi: 1, first_contributor: null },
                       { item_key: "100000003", multi: 0, first_contributor: null }]);

  // Same columns as a fresh schema.sql database, and schema.sql still applies on top.
  await exec(w.db, sql("schema.sql"));
  for (const col of ["snapshots", "window_start", "window_rows"]) assert.ok((await columns("contributors")).includes(col));
  for (const col of ["first_contributor", "multi"]) assert.ok((await columns("item_ref")).includes(col));
});

test("the worker runs on the migrated database", async () => {
  const k = await w.api("/v1/admin/keys", { key: ADMIN_TOKEN, body: { name: "after" } });
  const t = now() - 60;
  // 100000001 is protected (samples 3, multi 1): a 100x price from a brand-new key is an outlier.
  const snapshots = [[1, "100000001", t, 1000, 1], [1, "100000001", t + 1, 12, 1], [1, "100000009", t, 5, 1]];
  const up = await w.api("/v1/upload", { key: k.body.key, body: { snapshots } });
  assert.deepEqual(up.body.snapshots, { inserted: 2, rejected: 0, outliers: 1 });
  const list = await w.api("/v1/admin/keys", { key: ADMIN_TOKEN });
  assert.deepEqual(list.body.contributors.map(c => c.snapshots), [3, 0, 2]);
  const first = await w.db.prepare("SELECT first_contributor FROM item_ref WHERE item_key = '100000001'").first();
  assert.equal(first.first_contributor, k.body.id);           // filled in by the first upload after the migration
});

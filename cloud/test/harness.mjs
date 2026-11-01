// Runs the worker in-process with wrangler's test harness. D1 lives in memory, nothing remote is touched.
import { createTestHarness, unstable_splitSqlQuery } from "wrangler";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export const ADMIN_TOKEN = "test-admin-token-0123456789";
const root = fileURLToPath(new URL("..", import.meta.url));

export const sql = file => readFileSync(new URL(file, new URL("..", import.meta.url)), "utf8");

// Starts the worker; `schema` is the SQL text to apply first (null: an empty database).
export async function start(schema = sql("schema.sql")) {
  const server = createTestHarness({
    root, workers: [{ configPath: "./wrangler.toml", vars: { OPEN_REGISTRATION: "true" }, secrets: { ADMIN_TOKEN } }],
  });
  try {
    await server.listen();
    const env = await server.getWorker().getEnv();
    if (schema) await exec(env.DB, schema);
    return { server, db: env.DB, api: (path, opts) => api(server, path, opts) };
  } catch (e) {
    await server.close();
    throw e;
  }
}

export async function exec(db, text) {
  await db.batch(unstable_splitSqlQuery(text).map(s => db.prepare(s)));
}

// {status, body}; `key` goes into the Authorization header, `body` is sent as JSON (strings as they are).
async function api(server, path, { key, body, method, headers = {} } = {}) {
  const init = { method: method || (body === undefined ? "GET" : "POST"), headers: { ...headers } };
  if (key) init.headers.Authorization = `Bearer ${key}`;
  if (body !== undefined) init.body = typeof body === "string" ? body : JSON.stringify(body);
  const res = await server.fetch(path, init);
  const text = await res.text();
  let parsed;
  try { parsed = JSON.parse(text); } catch { parsed = text; }
  return { status: res.status, body: parsed };
}

export const now = () => Date.now() / 1000;

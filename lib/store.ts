// Where matches are kept. With DATABASE_URL or POSTGRES_URL set (Supabase,
// Neon or any Postgres; Vercel's database integrations set one of these for
// you) they go in the `matches` table. Without it, they go in a JSON file
// under ./data, which is handy for trying the site on your own computer.

import "server-only";
import fs from "node:fs/promises";
import path from "node:path";
import postgres from "postgres";
import type { Match } from "./types";
import { normalize, NORMALIZER_VERSION } from "./normalize";

export type SaveResult = "created" | "exists";

interface Store {
  save(match: Match, raw: unknown, uploadedBy: string | null): Promise<SaveResult>;
  all(): Promise<Match[]>;
  count(): Promise<number>;
  forEachRaw(fn: (id: string, raw: any) => Promise<void> | void): Promise<void>;
  updateSummary(id: string, match: Match): Promise<void>;
  getSetting(key: string): Promise<string | null>;
  /** Stores the value only if the key is unset, then returns whatever is stored. */
  initSetting(key: string, value: string): Promise<string>;
  setSetting(key: string, value: string): Promise<void>;
}

/** The Postgres connection string, cleaned of options postgres.js doesn't understand. */
export function databaseUrl(): string | null {
  const raw = process.env.DATABASE_URL || process.env.POSTGRES_URL || process.env.POSTGRES_PRISMA_URL;
  if (!raw) return null;
  try {
    const u = new URL(raw);
    for (const k of [...u.searchParams.keys()]) if (k !== "sslmode") u.searchParams.delete(k);
    return u.toString();
  } catch {
    return raw;
  }
}

// --------------------------------------------------------------------------
// Postgres
// --------------------------------------------------------------------------

let sqlClient: ReturnType<typeof postgres> | null = null;
let schemaReady: Promise<void> | null = null;

function sql() {
  if (!sqlClient) {
    const url = databaseUrl()!;
    const local = /@(localhost|127\.0\.0\.1)[:/]/.test(url);
    sqlClient = postgres(url, {
      ssl: local ? false : "require",
      prepare: false, // works with Supabase's pooler (port 6543) and serverless hosts
      max: 3,
      idle_timeout: 20,
      onnotice: () => {},
    });
  }
  return sqlClient;
}

async function ensureSchema() {
  if (!schemaReady) {
    schemaReady = (async () => {
      const db = sql();
      await db`
        create table if not exists matches (
          id text primary key,
          played_at timestamptz not null,
          summary jsonb not null,
          raw jsonb not null,
          uploaded_by text,
          inserted_at timestamptz not null default now()
        )`;
      await db`create index if not exists matches_played_at_idx on matches (played_at desc)`;
      await db`create table if not exists settings (key text primary key, value text not null)`;
    })().catch((e) => {
      schemaReady = null;
      throw e;
    });
  }
  return schemaReady;
}

const pgStore: Store = {
  async save(match, raw, uploadedBy) {
    await ensureSchema();
    const rows = await sql()`
      insert into matches (id, played_at, summary, raw, uploaded_by)
      values (${match.id}, ${new Date(match.playedAt).toISOString()}::timestamptz,
              ${sql().json(match as any)}, ${sql().json(raw as any)}, ${uploadedBy})
      on conflict (id) do nothing
      returning id`;
    return rows.length ? "created" : "exists";
  },
  async all() {
    await ensureSchema();
    const rows = await sql()`select summary from matches order by played_at desc`;
    return rows.map((r) => r.summary as Match);
  },
  async count() {
    await ensureSchema();
    const [row] = await sql()`select count(*)::int as n from matches`;
    return row.n as number;
  },
  async forEachRaw(fn) {
    await ensureSchema();
    const rows = await sql()`select id, raw from matches`;
    for (const r of rows) await fn(r.id as string, r.raw);
  },
  async updateSummary(id, match) {
    await sql()`update matches set summary = ${sql().json(match as any)} where id = ${id}`;
  },
  async getSetting(key) {
    await ensureSchema();
    const [row] = await sql()`select value from settings where key = ${key}`;
    return row ? (row.value as string) : null;
  },
  async setSetting(key, value) {
    await ensureSchema();
    await sql()`insert into settings (key, value) values (${key}, ${value}) on conflict (key) do update set value = excluded.value`;
  },
  async initSetting(key, value) {
    await ensureSchema();
    await sql()`insert into settings (key, value) values (${key}, ${value}) on conflict (key) do nothing`;
    const [row] = await sql()`select value from settings where key = ${key}`;
    return row.value as string;
  },
};

// --------------------------------------------------------------------------
// Local JSON file (development / demo only)
// --------------------------------------------------------------------------

interface FileRow { summary: Match; raw: unknown; uploadedBy: string | null; insertedAt: number }

const FILE = path.join(process.cwd(), "data", "matches.json");
const SETTINGS_FILE = path.join(process.cwd(), "data", "settings.json");

async function readSettings(): Promise<Record<string, string>> {
  try {
    return JSON.parse(await fs.readFile(SETTINGS_FILE, "utf8"));
  } catch {
    return {};
  }
}

async function readFile(): Promise<Record<string, FileRow>> {
  try {
    return JSON.parse(await fs.readFile(FILE, "utf8"));
  } catch {
    return {};
  }
}

async function writeFile(rows: Record<string, FileRow>) {
  await fs.mkdir(path.dirname(FILE), { recursive: true });
  const tmp = FILE + ".tmp";
  await fs.writeFile(tmp, JSON.stringify(rows));
  await fs.rename(tmp, FILE);
}

let fileLock: Promise<unknown> = Promise.resolve();
function locked<T>(fn: () => Promise<T>): Promise<T> {
  const next = fileLock.then(fn, fn);
  fileLock = next.catch(() => {});
  return next;
}

const fileStore: Store = {
  save(match, raw, uploadedBy) {
    return locked(async () => {
      const rows = await readFile();
      if (rows[match.id]) return "exists" as const;
      rows[match.id] = { summary: match, raw, uploadedBy, insertedAt: Date.now() };
      await writeFile(rows);
      return "created" as const;
    });
  },
  async all() {
    const rows = await readFile();
    return Object.values(rows).map((r) => r.summary).sort((a, b) => b.playedAt - a.playedAt);
  },
  async count() {
    return Object.keys(await readFile()).length;
  },
  async forEachRaw(fn) {
    for (const [id, r] of Object.entries(await readFile())) await fn(id, r.raw);
  },
  updateSummary(id, match) {
    return locked(async () => {
      const rows = await readFile();
      if (rows[id]) rows[id].summary = match;
      await writeFile(rows);
    });
  },
  async getSetting(key) {
    return (await readSettings())[key] ?? null;
  },
  setSetting(key, value) {
    return locked(async () => {
      const all = await readSettings();
      all[key] = value;
      await fs.mkdir(path.dirname(SETTINGS_FILE), { recursive: true });
      await fs.writeFile(SETTINGS_FILE, JSON.stringify(all));
    });
  },
  initSetting(key, value) {
    return locked(async () => {
      const all = await readSettings();
      if (!all[key]) {
        all[key] = value;
        await fs.mkdir(path.dirname(SETTINGS_FILE), { recursive: true });
        await fs.writeFile(SETTINGS_FILE, JSON.stringify(all));
      }
      return all[key];
    });
  },
};

// --------------------------------------------------------------------------

export function store(): Store {
  if (databaseUrl()) return pgStore;
  if (process.env.VERCEL) {
    throw new Error("No database is connected. In Vercel, open the project's Storage tab and connect a Postgres database.");
  }
  return fileStore;
}

export function storageKind(): "postgres" | "file" {
  return databaseUrl() ? "postgres" : "file";
}

/** Re-run the normalizer over every stored game (after updating the site). */
export async function renormalizeAll(): Promise<{ updated: number; failed: number }> {
  const s = store();
  let updated = 0;
  let failed = 0;
  await s.forEachRaw(async (id, raw) => {
    try {
      const m = normalize(raw);
      m.id = id;
      await s.updateSummary(id, m);
      updated++;
    } catch {
      failed++;
    }
  });
  return { updated, failed };
}

export { NORMALIZER_VERSION };

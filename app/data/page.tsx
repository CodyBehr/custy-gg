// Private: how the expert replay data is coming in. Only with the DASHBOARD_KEY cookie (see lib/dash.ts).
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { dashAllowed } from "@/lib/dash";
import { listObjects } from "@/lib/r2";
import { store } from "@/lib/store";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Data", robots: { index: false } };

const GOAL = 2000;
const HOUR = 3_600_000;
const REGION = (key: string) => {
  const f = key.split("/").pop() ?? "";
  const m = /^([A-Z0-9]+)_\d+/.exec(f);
  return m ? m[1].replace(/\d+$/, "") : "NA";
};
const ago = (t: number) => {
  const s = (Date.now() - t) / 1000;
  return s < 90 ? "just now" : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 172800 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`;
};
const clock = (t: number) => new Date(t).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export default async function Data() {
  if (!(await dashAllowed())) notFound();
  const { R2_ACCOUNT_ID: acc, R2_ACCESS_KEY_ID: akid, R2_SECRET_ACCESS_KEY: secret, R2_BUCKET: bucket } = process.env;
  let games: { key: string; size: number; at: number }[] = [];
  let err: string | null = null;
  try {
    games = acc && akid && secret ? (await listObjects(acc, akid, secret, bucket || "custy-data", "games/")).filter((g) => g.key.endsWith(".json.gz")) : [];
  } catch (e: any) { err = String(e?.message ?? e); }

  const s = store();
  const keys = await s.getSettings(["expert_contrib_v2", "expert_crawl_v2", "expert_crawl_v2_euw1", "expert_crawl_v2_eun1", "expert_crawl_v2_kr"]).catch(() => ({} as Record<string, string>));
  const contrib = (() => { try { return JSON.parse(keys.expert_contrib_v2 ?? "{}"); } catch { return {}; } })() as { counts?: Record<string, number>; last?: Record<string, number> };
  const crawls = Object.entries(keys).filter(([k]) => k.startsWith("expert_crawl_v2")).map(([k, v]) => {
    try {
      const st = JSON.parse(v);
      return { region: k === "expert_crawl_v2" ? "NA" : k.split("_").pop()!.toUpperCase().replace(/\d+$/, ""), patch: st.patch, queue: st.queue?.length ?? 0, ladder: st.ladder?.length ?? 0, last: st.last as { at: number; served: number; note: string | null } | undefined };
    } catch { return null; }
  }).filter(Boolean) as { region: string; patch: string; queue: number; ladder: number; last?: { at: number; served: number; note: string | null } }[];

  const total = games.length;
  const byPatch = new Map<string, number>(), byRegion = new Map<string, number>();
  for (const g of games) {
    const patch = g.key.split("/")[1];
    byPatch.set(patch, (byPatch.get(patch) ?? 0) + 1);
    const r = REGION(g.key); byRegion.set(r, (byRegion.get(r) ?? 0) + 1);
  }
  const now = Date.now();
  const day = games.filter((g) => now - g.at < 24 * HOUR).length;
  const lastAt = games.reduce((m, g) => Math.max(m, g.at), 0);
  const eta = day > 0 && total < GOAL ? Math.ceil((GOAL - total) / day) : null;
  // per hour, last 48 h (oldest first)
  const hours = Array.from({ length: 48 }, (_, i) => {
    const end = Math.floor(now / HOUR) * HOUR + HOUR - (47 - i) * HOUR;
    return { start: end - HOUR, n: games.filter((g) => g.at >= end - HOUR && g.at < end).length };
  });
  const maxH = Math.max(10, ...hours.map((h) => h.n));
  const people = Object.entries(contrib.counts ?? {}).map(([who, n]) => ({ who, n, last: contrib.last?.[who] })).sort((a, b) => b.n - a.n);
  const mb = games.reduce((t, g) => t + g.size, 0) / 1e6;

  const W = 960, H = 160, bw = W / 48;
  return (
    <>
      <div className="head"><h1>Expert data</h1><p className="muted">Replays boiled down and uploaded by custy coach. Updated live.</p></div>
      {err ? <div className="panel" style={{ padding: 18, marginBottom: 16 }}><p className="err">Couldn&apos;t read storage: {err}</p></div> : null}
      <div className="panel" style={{ padding: 18, marginBottom: 16, display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))", gap: 16 }}>
        <div><div className="muted">Games</div><div style={{ fontSize: 34, fontWeight: 800 }}>{total.toLocaleString()}</div><div className="muted">{mb.toFixed(0)} MB stored</div></div>
        <div><div className="muted">Last 24 hours</div><div style={{ fontSize: 34, fontWeight: 800 }}>{day}</div><div className="muted">{lastAt ? `last one ${ago(lastAt)}` : "none yet"}</div></div>
        <div><div className="muted">To {GOAL.toLocaleString()}</div><div style={{ fontSize: 34, fontWeight: 800 }}>{Math.min(100, Math.round((total / GOAL) * 100))}%</div><div className="muted">{total >= GOAL ? "reached" : eta ? `about ${eta} day${eta > 1 ? "s" : ""} at this pace` : "no pace yet"}</div></div>
        <div><div className="muted">By patch</div>{[...byPatch].sort().reverse().map(([p, n]) => <div key={p}><b>{p}</b> <span className="muted">{n}</span></div>)}</div>
        <div><div className="muted">By region</div>{[...byRegion].sort((a, b) => b[1] - a[1]).map(([r, n]) => <div key={r}><b>{r}</b> <span className="muted">{n}</span></div>)}</div>
      </div>
      <div className="panel" style={{ padding: 18, marginBottom: 16 }}>
        <h2 style={{ marginBottom: 10 }}>Games per hour, last 48 hours</h2>
        <svg viewBox={`0 0 ${W} ${H + 18}`} style={{ width: "100%", height: "auto" }} role="img" aria-label="Games uploaded per hour">
          {[0.5, 1].map((f) => <line key={f} x1={0} x2={W} y1={H - f * H} y2={H - f * H} stroke="var(--line-soft)" />)}
          <text x={2} y={12} fill="var(--faint)" fontSize={11}>{maxH}</text>
          {hours.map((h, i) => (
            <g key={i}>
              <rect x={i * bw + 1} y={H - (h.n / maxH) * H} width={bw - 2} height={(h.n / maxH) * H} rx={2} fill={h.n ? "var(--blue)" : "transparent"}><title>{`${clock(h.start)}: ${h.n}`}</title></rect>
              {new Date(h.start).getUTCHours() === 5 ? <text x={i * bw} y={H + 14} fill="var(--faint)" fontSize={11}>{new Date(h.start).toLocaleDateString("en-US", { timeZone: "America/New_York", weekday: "short" })}</text> : null}
            </g>
          ))}
        </svg>
      </div>
      <div className="panel" style={{ padding: 18, marginBottom: 16 }}>
        <h2 style={{ marginBottom: 10 }}>Who&apos;s sending</h2>
        {people.length ? (
          <table className="t"><thead><tr><th>Riot ID</th><th>Games</th><th>Last sent</th></tr></thead>
            <tbody>{people.map((p) => <tr key={p.who}><td>{p.who}</td><td>{p.n}</td><td className="muted">{p.last ? ago(p.last) : "before tracking"}</td></tr>)}</tbody></table>
        ) : <p className="muted">Nobody yet.</p>}
      </div>
      <div className="panel" style={{ padding: 18, marginBottom: 16 }}>
        <h2 style={{ marginBottom: 10 }}>Game picker</h2>
        {crawls.length ? (
          <table className="t"><thead><tr><th>Region</th><th>Patch</th><th>Ready to hand out</th><th>Last request</th><th>Status</th></tr></thead>
            <tbody>{crawls.map((c) => <tr key={c.region}><td>{c.region}</td><td>{c.patch}</td><td>{c.queue}</td><td className="muted">{c.last ? ago(c.last.at) : "—"}</td><td>{c.last?.note ?? (c.last ? "OK" : "—")}</td></tr>)}</tbody></table>
        ) : <p className="muted">No requests yet.</p>}
      </div>
    </>
  );
}

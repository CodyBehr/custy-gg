// TEMPORARY: shows which role-related fields real uploaded games contain. Removed after checking.
import { NextResponse } from "next/server";
import { getDataset } from "@/lib/stats";
import { store } from "@/lib/store";

export const dynamic = "force-dynamic";

function walk(o: any, prefix: string, out: Set<string>) {
  if (!o || typeof o !== "object") return;
  for (const [k, v] of Object.entries(o)) {
    const p = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) walk(v, p, out);
    else out.add(p);
  }
}

export async function GET() {
  const d = await getDataset();
  const games = d.matches.filter((m) => !m.remake).slice(0, 4);
  const out: any[] = [];
  const allKeys = new Set<string>();
  for (const m of games) {
    const raw = await store().getRaw(m.id);
    const tl = await store().getTimeline(m.id);
    const parts: any[] = raw?.participants ?? [];
    for (const p of parts) walk(p, "", allKeys);
    const interesting = (p: any) => {
      const hits: Record<string, unknown> = {};
      const keys = new Set<string>(); walk(p, "", keys);
      for (const k of keys) if (/role|quest|position|lane|augment|bound|subteam|placement/i.test(k)) hits[k] = k.split(".").reduce((o: any, x) => o?.[x], p);
      return hits;
    };
    out.push({
      id: m.id,
      guessed: m.players.map((p) => `${p.teamId} ${p.name}: ${p.role || "?"}`),
      raw: parts.map((p) => ({
        team: p.teamId, champ: p.championId, spells: [p.spell1Id, p.spell2Id],
        items: [0, 1, 2, 3, 4, 5, 6].map((i) => p.stats?.[`item${i}`]),
        ...interesting(p),
      })),
      timelinePositionsAvailable: Boolean(tl),
    });
  }
  return NextResponse.json({ participantFieldNames: [...allKeys].sort(), games: out });
}

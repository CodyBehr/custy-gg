// How many expert games each person's custy coach has sent, by Riot ID, for the Recordings tab.
//   GET /api/experts/contributors   (Authorization: Bearer <ingest key>) -> { people: [{ who, n }], total }
import { NextResponse } from "next/server";
import { checkIngestKey } from "@/lib/ingest-key";
import { store } from "@/lib/store";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  if (!(await checkIngestKey(req.headers.get("authorization")))) {
    return NextResponse.json({ error: "Wrong ingest key" }, { status: 401 });
  }
  let counts: Record<string, number> = {};
  try { counts = JSON.parse((await store().getSetting("expert_contrib")) ?? "{}").counts ?? {}; } catch {}
  const people = Object.entries(counts).map(([who, n]) => ({ who, n })).sort((a, b) => b.n - a.n);
  return NextResponse.json({ people, total: people.reduce((t, p) => t + p.n, 0) });
}

import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { getStatic } from "@/lib/ddragon";
import { clock, getDataset } from "@/lib/stats";
import type { MatchTeam } from "@/lib/types";
import { when } from "@/components/ui";
import { Board } from "@/components/scoreboard";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const d = await getDataset();
  const m = d.matches.find((x) => x.id === decodeURIComponent(id));
  return { title: m ? `Game on ${when(m.playedAt).day}` : "Game" };
}

export default async function MatchPage({ params }: Props) {
  const { id } = await params;
  const [d, s] = await Promise.all([getDataset(), getStatic()]);
  const m = d.matches.find((x) => x.id === decodeURIComponent(id));
  if (!m) notFound();

  const w = when(m.playedAt);
  const blue = m.teams.find((t) => t.teamId === 100)!;
  const red = m.teams.find((t) => t.teamId === 200)!;
  const winnerFirst = [...m.teams].sort((a, b) => Number(b.win) - Number(a.win));

  return (
    <>
      <p className="sub" style={{ marginBottom: 14 }}>
        {w.long} at {w.time}, {clock(m.duration)} long{m.remake ? ". Remake, not counted in stats." : "."}
      </p>
      <section className="verdict">
        <TeamHead t={blue} label="Blue side" />
        <div className="mid">
          <div className="kills">{blue.kills} : {red.kills}</div>
          kills
        </div>
        <TeamHead t={red} label="Red side" right />
      </section>

      {winnerFirst.map((t) => (
        <Board key={t.teamId} s={s} m={m} t={t} mvp={d.mvpOf.get(m.id)} deltas={d.ratingDelta} scores={d.scores} />
      ))}
    </>
  );
}

function TeamHead({ t, label, right }: { t: MatchTeam; label: string; right?: boolean }) {
  return (
    <div className={right ? "right" : ""}>
      <div className={`team-name ${t.win ? "won" : "lost"}`}>{t.win ? "Victory" : "Defeat"}</div>
      <div className="objs">
        {label}: {t.towers} towers, {t.dragons} dragons, {t.barons} barons, {(t.gold / 1000).toFixed(1)}k gold
      </div>
    </div>
  );
}

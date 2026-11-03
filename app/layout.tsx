import type { Metadata } from "next";
import { Big_Shoulders, Schibsted_Grotesk } from "next/font/google";
import Link from "next/link";
import { Nav } from "@/components/nav";
import { PlayerSearch, type SearchOption } from "@/components/player-search";
import { getDataset } from "@/lib/stats";
import { AUTH_COOKIE, passwordToken, safeEqual } from "@/lib/auth";
import { cookies } from "next/headers";
import "./globals.css";

const display = Big_Shoulders({ subsets: ["latin"], variable: "--font-display", axes: ["opsz"] });
const body = Schibsted_Grotesk({ subsets: ["latin"], variable: "--font-body" });

const GROUP = process.env.NEXT_PUBLIC_GROUP_NAME || "custy.gg";

export const metadata: Metadata = {
  title: { default: GROUP, template: `%s · ${GROUP}` },
  description: "Stats for our League of Legends custom games.",
  robots: { index: false, follow: false },
};

function Brand() {
  const dot = GROUP.lastIndexOf(".");
  if (dot > 0) return <>{GROUP.slice(0, dot)}<span>{GROUP.slice(dot)}</span></>;
  return <>{GROUP}</>;
}

async function searchOptions(): Promise<SearchOption[]> {
  // Behind a group password, don't hand player names to someone on the login page.
  const expected = await passwordToken();
  if (expected) {
    const given = (await cookies()).get(AUTH_COOKIE)?.value ?? "";
    if (!given || !safeEqual(given, expected)) return [];
  }
  try {
    const d = await getDataset();
    return d.players.map((p) => ({ puuid: p.puuid, label: `${p.name}#${p.tag}` }));
  } catch {
    return []; // database not connected yet; the pages themselves explain it
  }
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const options = await searchOptions();
  return (
    <html lang="en" className={`${display.variable} ${body.variable}`}>
      <body>
        <header className="top">
          <div className="wrap">
            <Link href="/" className="brand"><Brand /></Link>
            <Nav />
            <div className="top-search"><PlayerSearch options={options} /></div>
          </div>
        </header>
        <main>
          <div className="wrap">{children}</div>
        </main>
        <footer className="foot">
          <div className="wrap">
            {GROUP} isn&apos;t endorsed by Riot Games and doesn&apos;t reflect the views or opinions of Riot Games or anyone
            officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are
            trademarks or registered trademarks of Riot Games, Inc.
          </div>
        </footer>
      </body>
    </html>
  );
}

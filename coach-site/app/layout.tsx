import type { Metadata } from "next";
import Link from "next/link";
import SearchBox from "@/components/SearchBox";
import { BRAND, TAGLINE } from "@/lib/brand";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: `${BRAND}: League of Legends stats and game reviews`, template: `%s | ${BRAND}` },
  description: `Look up any League of Legends player's rank and match history. ${TAGLINE}`,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="top">
          <div className="wrap top-inner">
            <Link href="/" className="logo">
              <span className="logo-mark" aria-hidden>◐</span> {BRAND} <span className="beta">beta</span>
            </Link>
            <div className="top-search"><SearchBox /></div>
            <Link href="/download" className="btn btn-sm">Download the app</Link>
          </div>
        </header>
        <main className="wrap">{children}</main>
        <footer className="foot">
          <div className="wrap">
            <p>
              {BRAND} isn&apos;t endorsed by Riot Games and doesn&apos;t reflect the views or opinions of Riot Games or
              anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated
              properties are trademarks or registered trademarks of Riot Games, Inc.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}

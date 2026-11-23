import Link from "next/link";
import SearchBox from "@/components/SearchBox";
import { BRAND } from "@/lib/brand";

export default function Home() {
  return (
    <>
      <section className="hero">
        <h1>See what you <em>missed</em>.</h1>
        <p>Look up anyone&apos;s rank and match history for free. Then let the {BRAND} app show you where your games were won and lost.</p>
        <SearchBox big />
      </section>

      <div className="cards">
        <div className="card">
          <h3>Look anyone up</h3>
          <p>Rank, LP, win rate and recent games for any player on any server. No account needed.</p>
        </div>
        <div className="card">
          <h3>Review your games</h3>
          <p>The app reads your replays and shows the moments that decided your lane: trades, ganks, deaths and timings.</p>
        </div>
        <div className="card">
          <h3>Compare with experts</h3>
          <p>Your CS, gold, builds and backs next to Master+ players on the same champion and role.</p>
        </div>
      </div>

      <div className="promo">
        <div>
          <h2>Free during the beta</h2>
          <p>Windows app. Everything is free while we test it. Tell us what you think.</p>
        </div>
        <Link href="/download" className="btn">Get the {BRAND} app</Link>
      </div>
    </>
  );
}

import { REGIONS } from "@/lib/regions";

/** Plain GET form, so it works without JavaScript. /search turns it into a profile URL. */
export default function SearchBox({ big = false, region = "na", value = "" }: { big?: boolean; region?: string; value?: string }) {
  return (
    <form action="/search" method="get" className={big ? "search search-big" : "search"}>
      <select name="region" defaultValue={region} aria-label="Region">
        {REGIONS.map((r) => (
          <option key={r.slug} value={r.slug}>{r.slug.toUpperCase()}</option>
        ))}
      </select>
      <input name="q" defaultValue={value} placeholder="Riot ID, e.g. Faker#KR1" aria-label="Riot ID" autoComplete="off" required />
      <button type="submit">{big ? "Search" : "Go"}</button>
    </form>
  );
}

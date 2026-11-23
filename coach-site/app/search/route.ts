// /search?region=na&q=Name%23TAG -> redirect to /na/Name-TAG
import { NextResponse } from "next/server";
import { parseRiotId, profilePath, regionBySlug } from "@/lib/regions";

export function GET(req: Request) {
  const url = new URL(req.url);
  const region = regionBySlug(url.searchParams.get("region") || "na") ?? regionBySlug("na")!;
  const id = parseRiotId(url.searchParams.get("q") || "", region);
  if (!id) return NextResponse.redirect(new URL("/", req.url));
  return NextResponse.redirect(new URL(profilePath(region, id.name, id.tag), req.url));
}

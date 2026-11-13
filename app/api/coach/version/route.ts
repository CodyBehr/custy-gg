// GET /api/coach/version -> { version } of custy coach (custy-coach.exe) this site serves.
import { versionResponse } from "@/lib/app-exe";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const GET = () => versionResponse("custy-coach");

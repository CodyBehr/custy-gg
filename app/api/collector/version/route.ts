// GET /api/collector/version -> { version } of the custom-game uploader (custy-collector.exe) this site serves.
import { versionResponse } from "@/lib/app-exe";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const GET = () => versionResponse("custy-collector");

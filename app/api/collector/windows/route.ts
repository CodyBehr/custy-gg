// GET /api/collector/windows -> custy-collector.exe (uploads custom games), linked to this site.
import { downloadResponse } from "@/lib/app-exe";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const GET = (req: Request) => downloadResponse("custy-collector", req);

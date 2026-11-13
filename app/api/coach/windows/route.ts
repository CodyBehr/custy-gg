// GET /api/coach/windows -> custy-coach.exe (game review), linked to this site.
import { downloadResponse } from "@/lib/app-exe";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const GET = (req: Request) => downloadResponse("custy-coach", req);

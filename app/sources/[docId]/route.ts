import { readFile } from "node:fs/promises";
import { getConferenceSourcePath } from "@/lib/conference-data";

export const runtime = "nodejs";

type Ctx = { params: Promise<{ docId: string }> };

export async function GET(_request: Request, { params }: Ctx) {
  const { docId } = await params;
  const sourcePath = await getConferenceSourcePath(docId);
  if (!sourcePath) {
    return Response.json({ error: "source not found" }, { status: 404 });
  }

  try {
    const bytes = await readFile(sourcePath);
    const body = new Uint8Array(bytes);
    return new Response(body.buffer, {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `inline; filename="${docId}.pdf"`,
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return Response.json({ error: "source not found" }, { status: 404 });
  }
}

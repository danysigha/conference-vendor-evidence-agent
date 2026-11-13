import { getConferenceWorkbook } from "@/lib/conference-data";

export const runtime = "nodejs";

export async function GET() {
  try {
    const { filename, bytes } = await getConferenceWorkbook();
    const body = new Uint8Array(bytes);
    return new Response(body.buffer, {
      headers: {
        "Content-Type":
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": `attachment; filename="${filename}"`,
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return Response.json({ error: "conference directory unavailable" }, { status: 503 });
  }
}

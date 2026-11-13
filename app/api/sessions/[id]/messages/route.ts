import type { BetaManagedAgentsUserMessageEventParams } from "@anthropic-ai/sdk/resources/beta/sessions/events";
import { client } from "@/lib/anthropic";
import { seedConferenceFiles } from "@/lib/conference-data";
import { messageText, type AttachedFileRef } from "@/lib/managed-agents/events";
import { uploadAndMountAt } from "@/lib/managed-agents/session-files";
import { ownedSession } from "@/lib/owned-session";
import { jsonError } from "@/lib/sse";

// POST /api/sessions/[id]/messages {text, files?: [{filename, mountPath}]}
//
// One user turn. The browser must already have the tail
// (/api/sessions/[id]/stream) open before calling this: the reply arrives on
// the stream, not on this response. Files were uploaded and mounted into the
// sandbox at attach time (POST /api/sessions/[id]/files); here we just tell the
// agent where they landed so it can `read` them.

type Ctx = { params: Promise<{ id: string }> };

const TITLE_MAX = 60;
const TEXT_MAX = 20_000;
const preparedSessions = new Set<string>();
const preparingSessions = new Map<string, Promise<void>>();

async function mapLimit<T>(
  items: readonly T[],
  limit: number,
  worker: (item: T) => Promise<void>,
) {
  let index = 0;
  const runners = Array.from(
    { length: Math.min(limit, items.length) },
    async () => {
      while (index < items.length) {
        const item = items[index++]!;
        await worker(item);
      }
    },
  );
  await Promise.all(runners);
}

async function ensureConferenceData(sessionId: string): Promise<void> {
  if (preparedSessions.has(sessionId)) return;
  const current = preparingSessions.get(sessionId);
  if (current) return current;

  const preparation = (async () => {
    const mounted = new Set<string>();
    for await (const resource of client.beta.sessions.resources.list(sessionId)) {
      if (resource.type === "file") mounted.add(resource.mount_path);
    }
    const files = (await seedConferenceFiles()).filter(
      ({ mountPath }) => !mounted.has(mountPath),
    );
    await mapLimit(files, 4, ({ file, mountPath }) =>
      uploadAndMountAt(sessionId, file, mountPath).then(() => undefined),
    );
    preparedSessions.add(sessionId);
  })();

  preparingSessions.set(sessionId, preparation);
  try {
    await preparation;
  } finally {
    preparingSessions.delete(sessionId);
  }
}

export async function POST(request: Request, { params }: Ctx) {
  const { id } = await params;
  if (!request.headers.get("content-type")?.includes("application/json")) {
    return jsonError(415, "expected application/json");
  }
  const session = await ownedSession(id);
  if (!session) return jsonError(404, "session not found");

  const body = (await request.json().catch(() => null)) as {
    text?: unknown;
    files?: unknown;
  } | null;
  const text = typeof body?.text === "string" ? body.text.trim() : "";
  const files: AttachedFileRef[] = Array.isArray(body?.files)
    ? body.files.filter(
        (f): f is AttachedFileRef =>
          !!f &&
          typeof (f as AttachedFileRef).filename === "string" &&
          typeof (f as AttachedFileRef).mountPath === "string",
      )
    : [];

  if (!text && files.length === 0) return jsonError(400, "message is empty");
  if (text.length > TEXT_MAX) return jsonError(400, "message too long");

  // Session creation stays fast so the browser can render the optimistic
  // message immediately. Conference data is mounted here, just before the
  // first turn uses it. Missing files are uploaded in parallel and existing
  // sessions skip the work.
  try {
    await ensureConferenceData(id);
  } catch {
    return jsonError(503, "conference data could not be prepared; try again");
  }

  const message: BetaManagedAgentsUserMessageEventParams = {
    type: "user.message",
    // messageText() is shared with the browser's optimistic bubble, so the
    // echoed event carries byte-identical text and reconciles cleanly.
    content: [{ type: "text", text: messageText(text, files) }],
  };

  await client.beta.sessions.events.send(id, { events: [message] });

  // The first real message names the conversation, so the sidebar and the
  // Console session list both show what it's about. An attachment-only send
  // (drop a CSV, empty text box — the app's front door) titles from the
  // filename. Fire-and-forget: a failed retitle must never fail the turn.
  if (session.title === "New chat" || session.title === "New conference question") {
    const title = (text || files[0]?.filename || "").replace(/\s+/g, " ").trim().slice(0, TITLE_MAX);
    if (title) {
      void client.beta.sessions.update(id, { title }).catch(() => {});
    }
  }

  return Response.json({ ok: true }, { status: 202 });
}

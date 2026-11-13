# assistant-ui × Claude Managed Agents

A conference exhibitor analyst in a chat window. [assistant-ui](https://www.assistant-ui.com/) provides the composer, thread, sidebar, and tool cards. One [Managed Agent](https://platform.claude.com/docs/en/managed-agents/overview) session per conversation holds the transcript, runs `bash` with pandas, and streams every step back as events.

This build is grounded in public data from the [Generative AI Summit Boston 2026](https://world.aiacceleratorinstitute.com/location/boston/partners): 28 partner companies, 31 agenda entries, 47 sourced speaker records, 67 captured company pages, six exhibitor flyers, and 281 page-backed capability claims. The spreadsheet answers directory, agenda, coverage, and capability questions; website and brochure sources remain attached to every extracted claim.

```
sidebar ──▶ /api/sessions ─────────────────────────▶ /v1/sessions (list, create, archive)
        ──▶ /api/sessions/{id}/events ─────────────────▶ /v1/sessions/{id}/events (replay)

thread ──▶ /api/sessions/{id}/stream (SSE, opens first) ─▶ session event stream
       ──▶ /api/sessions/{id}/messages ───────────────▶ user.message
                                                            │
       reducer folds every event into            ┌────────┴─────────┐
       ThreadMessageLike[]:                       │ analyst (sonnet) │
         agent.message ─▶ streamed text            │ bash · pandas    │
         agent.tool_use ─▶ terminal / search /     │ web_search       │
                            file / diff card       │ show_chart       │
         status_idle{requires_action} ─▶ ┐          └──────────────────┘
                                          Allow/Deny gate on the bash card
       ──▶ /api/sessions/{id}/confirm ──────────────▶ user.tool_confirmation
       ──▶ /api/sessions/{id}/files (upload) ───────▶ Files API + resources.add
```

The only credential is Anthropic auth. `npm run dev`, open `localhost:3000`, and ask a question about the partner directory or supplied flyers. A new session also mounts the directory CSV, workbook, document join table, and extracted flyer Markdown automatically.

## Why this pairing

An agent app has two halves that never get built at the same time. The chat UI wants a message array to render and callbacks to fire: assistant-ui gives you the primitives (composer, thread, tool cards, an approval gate) and asks you to bring the runtime. The agent wants a durable place to think, a sandbox to run code, and a loop that survives your tab closing: Managed Agents gives you the session and asks you to bring the surface. Each ships the half the other doesn't.

The join is one file. [`lib/managed-agents/reducer.ts`](lib/managed-agents/reducer.ts) is a pure function from a session's event log to assistant-ui's message model, and the same function runs over stored history and the live stream, so an old chat and a running one can never render differently. assistant-ui's `useExternalStoreRuntime` takes the folded array; its `useRemoteThreadListRuntime` takes the session list as the sidebar. There is no database anywhere in the app, because sessions already are one.

The event log carries more than text, and this is where assistant-ui earns its place. A `web_search` result is a structured list of sources, so it renders as source cards. An `edit` is an `old_string`/`new_string` pair, so it renders as a diff. And an `always_ask` tool call is a session that has *stopped and is waiting for a click*, which is exactly what assistant-ui's approval gate is for.

## Sessions are the thread list

Most chat apps grow a conversations table on day two. This one asks the Managed Agents API instead:

- **The sidebar** is a `RemoteThreadListAdapter` ([`session-list-adapter.ts`](lib/managed-agents/session-list-adapter.ts)) over `client.beta.sessions.list()`, filtered to sessions this quickstart created (a `metadata` tag). Thread id and session id are the same string.
- **New chat** calls `sessions.create()` from the adapter's `initialize()`, which assistant-ui invokes on the first message. The first message then retitles the session server-side, so the sidebar and the Anthropic Console show the same name.
- **Opening an old chat** replays `sessions.events.list()` through the reducer. Tool calls, approvals, denials, the chart: all rebuilt from the log, so nothing can be stale. Kill the server, restart, reload: every conversation comes back, because none of it ever lived here.
- **Archive and delete** are the sidebar's dropdown, mapped onto `sessions.archive()` and `sessions.delete()`.

Because a session id arrives from the browser and becomes an API path parameter, every route under `/api/sessions/[id]` first passes it through [`ownedSession()`](lib/owned-session.ts): the id must parse, resolve, belong to this quickstart's agent, carry our metadata tag, and not be archived. Files never exist outside a session either: uploads post to `/api/sessions/[id]/files` and downloads check the file id against that session's own file set before a byte moves. The server key can see the whole workspace; the gate is what keeps a guessed id from reading it.

## The approval gate

The agent's toolset sets `bash` to `permission_policy: always_ask` ([`agents/spreadsheet-analyst.md`](agents/spreadsheet-analyst.md)). When the analyst reaches for the shell, the session doesn't run the command. It emits the `agent.tool_use`, then parks:

```
session.status_idle { stop_reason: { type: "requires_action", event_ids: ["sevt_..."] } }
```

The reducer stamps `approval: { id }` onto that tool-call part and sets the message status to `requires-action`, which is all assistant-ui needs to render the gate. The terminal card shows the exact command with Allow and Deny under it; Deny takes an optional note. The click becomes:

```json
{ "type": "user.tool_confirmation", "tool_use_id": "sevt_...", "result": "deny",
  "deny_message": "Not on this box." }
```

The `tool_use_id` is the *event* id of the tool-use, and confirmations are batched into one send (two clicks in the same beat ride together, because racing sends can be rejected mid-resume). A denial reaches the agent as the tool's result, so it adjusts instead of retrying. Reload with the gate open and the buttons come back exactly where they were: the pending request is in the log, not in browser state.

Match the policy to the surface. `always_ask` belongs here because there is a human at a keyboard to answer it; a scheduled or headless deployment wants `always_allow` (or bash off), or the session parks forever waiting for a click that never comes.

## Token streaming and reasoning

The tail opens with `event_deltas: ["agent.message", "agent.thinking"]`. As the model writes, the session sends `event_start`, then `event_delta` text fragments, then the buffered `agent.message` that was always there; the reducer folds the fragments into the text part and reconciles when the buffered event lands (a preview is always a verbatim prefix of its final message). Previews are best-effort and never persisted, so an org without the streaming gate gets the same code path with replies arriving whole.

`agent.thinking` is a progress signal with no reasoning text in the current API, so it renders as an empty reasoning part: assistant-ui's chain-of-thought group shows "thinking" activity without the app inventing content. Don't promise streamed reasoning text; the API doesn't send it.

## Tool cards

Every tool the analyst can call has a card, registered as a render-only assistant-ui toolkit in [`components/tool-uis/`](components/tool-uis/) (no client `execute`, no build plugin):

| Tool | Card |
|---|---|
| `bash` | terminal: `$ command`, the approval gate, then stdout (error output in red) |
| `web_search` | the query as a chip, `search_result` blocks as source cards |
| `web_fetch` | the URL, then a preview of what came back |
| `read` / `write` / `glob` / `grep` | path or pattern, with collapsible output |
| `edit` | `old_string` → `new_string` as a unified diff (assistant-ui's `DiffViewer`) |
| `show_chart` | a custom, client-executed tool: an inline SVG chart |
| anything else | `ToolFallback` (MCP tools, other custom tools) |

`show_chart` is the one *custom* tool. Managed Agents doesn't run it: the session parks on it, the card draws the chart from the tool's input, and the session controller answers with a `user.custom_tool_result` ("Rendered to the user in the chat.") so the agent continues. Custom tools take a *result*, never a confirmation; sending `user.tool_confirmation` for one is a 400.

## Conference files and optional attachments

When a session is created, [`seedConferenceFiles()`](lib/conference-data.ts) uploads the conference data to `/mnt/session/uploads/conference/`. The CSV layer includes the company directory, flyer links, company profiles, website sources, capability claims, sessions, speakers, and speaker-session joins. The `.xlsx` is the formatted analysis workbook; `company_site_text.md` contains captured public website context; and `flyers/*.md` contains page-scoped OCR text. Original PDFs remain under `data/conference/raw/` and are served through `/sources/{doc_id}#page=N` for citations.

Refresh the public event and company-site data with:

```bash
npm install
python3 -m pip install -r requirements-ingest.txt
npm run ingest:conference
```

The crawler respects `robots.txt`, limits itself to a small set of public product and trust pages per company, captures crawl time and content hashes, and records blocked or unreachable sites instead of filling gaps from memory. Oracle currently rejects automated access, so it remains listing-only.

Users can still drop additional CSV, Excel, JSON, text, Markdown, or PDF files onto the composer. The attachment adapter uploads those files to the same session and appends their mount paths to the message.

Deliverables the analyst writes to `/mnt/session/outputs/` are meant to come back through `files.list({ scope_id })` as download chips. That query parameter is newer than the rest of the API and is not enabled on every organization yet; where it isn't, the call returns `400 unknown field scope_id`, [`session-files.ts`](lib/managed-agents/session-files.ts) catches it, and you get the upload chips without the download chips. The route and the membership check are written to the documented shape, so the chips light up the day the parameter reaches your org.

## Quickstart

```bash
cd managed-agents/assistant-ui
npm install
claude
```

Then ask: **"walk me through setting this up."** Claude reads [`skill.md`](./skill.md) and drives the whole thing. Or by hand:

```bash
ant auth login                  # or export ANTHROPIC_API_KEY (and put it in .env for the app)
ant apply agents environments   # one-time: one agent + one environment, IDs recorded in claude-lock.json
npm run dev                     # open http://localhost:3000
```

[`ant apply`](https://platform.claude.com/docs/en/cli-sdks-libraries/cli/apply) (the [`ant` CLI](https://platform.claude.com/docs/en/cli-sdks-libraries/cli/quickstart) 2.0 or later, `brew install anthropics/tap/ant`) reads the agent from [`agents/spreadsheet-analyst.md`](agents/spreadsheet-analyst.md), whose frontmatter holds the model and tools and whose prose is the system prompt, and the sandbox from [`environments/spreadsheet-analyst.yaml`](environments/spreadsheet-analyst.yaml). It shows the plan, creates both once you approve, and records their IDs in `claude-lock.json`, which the app reads. To change the agent, edit its file and run a bare `ant apply`: that publishes a new version of the same agent, and the next session uses it. This repository ignores `claude-lock.json`, since every reader creates their own resources. In a project of your own, commit it.

Try: *"Map the exhibitor directory and identify which companies have brochure evidence."* Then ask: *"Compare what Barndoor, C1.ai, and OmniTrust say about governance and runtime control."* You will see spreadsheet analysis, cited flyer pages, and an Allow/Deny gate on every `bash` command.

Token previews (`event_deltas`) are part of the 2026-07-01 Managed Agents update and are gated per organization. Without the streaming gate everything still works and replies arrive whole instead of streaming.

## Files

| | |
|---|---|
| `agents/spreadsheet-analyst.md` | The agent for `ant apply`: Claude Sonnet 5.5, tools (bash `always_ask`, the `show_chart` custom tool), system prompt |
| `environments/spreadsheet-analyst.yaml` | Its sandbox: cloud, open networking, pandas preinstalled |
| `lib/managed-agents/reducer.ts` | The bridge: event log → messages (pure, unit-tested) |
| `lib/managed-agents/session-controller.ts` | Per-session replay + live tail + send/confirm/interrupt, batched approvals |
| `lib/managed-agents/session-list-adapter.ts` | The sidebar's `RemoteThreadListAdapter` over the session list |
| `lib/managed-agents/runtime-provider.tsx` | `useRemoteThreadListRuntime` + per-session `useExternalStoreRuntime` |
| `lib/managed-agents/attachments.ts` | Composer attachments → Files API upload + sandbox mount |
| `lib/owned-session.ts` | The session ownership gate every route goes through |
| `app/api/sessions/**` | Route handlers: list/create/replay/tail/messages/confirm/files/interrupt |
| `data/conference/` | Partner CSVs, extracted flyer Markdown, and original PDFs |
| `scripts/scrape_conference.py` | Public agenda, speaker, company-site, capability, and provenance ingestion |
| `data/conference/sessions.csv` | Published agenda entries with tracks, times, descriptions, and source URLs |
| `data/conference/speakers.csv` | Speaker profiles, roles, companies, bios, and profile URLs |
| `data/conference/capabilities.csv` | Normalized capability claims backed by website or flyer evidence |
| `outputs/01a1d559-faf8-71f0-b349-e7d66663b9ea/` | Formatted exhibitor directory workbook |
| `components/tool-uis/` | The tool cards and the approval bar |
| `components/assistant-ui/`, `components/ui/` | assistant-ui copy-in components (see `components/NOTICE.md`) |
| `app/assistant.tsx` | Sidebar + thread + toolkit + suggestions, composed |
| `skill.md` | Setup walkthrough, gotchas, debugging |

Runtime is Node 22 with Next.js 16 (App Router). `@anthropic-ai/sdk` needs 0.109.0 or later: that release is the first with `event_deltas` and the session event helpers. `@assistant-ui/react` 0.14.27 is the first line with the `defineToolkit` / `Tools` API and the approval gate on `useExternalStoreRuntime`; the copy-in components under `components/` were generated against it (`npx assistant-ui add ...`) and are MIT-licensed by AgentbaseAI Inc.

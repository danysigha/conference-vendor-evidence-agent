import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import path from "node:path";

const root = process.cwd();
const dataDir = path.join(root, "data", "conference");

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;

  for (let index = 0; index < text.length; index++) {
    const char = text[index];
    if (char === '"') {
      if (quoted && text[index + 1] === '"') {
        field += '"';
        index++;
      } else {
        quoted = !quoted;
      }
    } else if (char === "," && !quoted) {
      row.push(field);
      field = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && text[index + 1] === "\n") index++;
      row.push(field);
      if (row.some(Boolean)) rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }

  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }

  const [headers, ...body] = rows;
  return body.map((values) =>
    Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""])),
  );
}

const exhibitors = parseCsv(
  await readFile(path.join(dataDir, "exhibitors.csv"), "utf8"),
);
const documents = parseCsv(
  await readFile(path.join(dataDir, "exhibitor_documents.csv"), "utf8"),
);
const sessions = parseCsv(
  await readFile(path.join(dataDir, "sessions.csv"), "utf8"),
);
const speakers = parseCsv(
  await readFile(path.join(dataDir, "speakers.csv"), "utf8"),
);
const speakerSessions = parseCsv(
  await readFile(path.join(dataDir, "speaker_sessions.csv"), "utf8"),
);
const capabilities = parseCsv(
  await readFile(path.join(dataDir, "capabilities.csv"), "utf8"),
);
const profiles = parseCsv(
  await readFile(path.join(dataDir, "company_profiles.csv"), "utf8"),
);
const sources = parseCsv(
  await readFile(path.join(dataDir, "company_sources.csv"), "utf8"),
);

assert.equal(exhibitors.length, 28, "expected 28 unique partner companies");
assert.equal(new Set(exhibitors.map((row) => row.exhibitor_id)).size, 28);
assert.equal(exhibitors.filter((row) => row.has_flyer === "true").length, 5);
assert.equal(documents.length, 6);
assert.equal(new Set(documents.map((row) => row.doc_id)).size, 6);
assert.equal(sessions.length, 31);
assert.equal(new Set(sessions.map((row) => row.session_id)).size, 31);
assert.ok(speakers.length >= 41, "expected at least 41 speaker records");
assert.equal(new Set(speakers.map((row) => row.speaker_id)).size, speakers.length);
assert.ok(speakerSessions.length >= 30);
assert.ok(capabilities.length >= 200, "expected a substantial capability dataset");
assert.ok(
  capabilities.every(
    (row) =>
      row.evidence_quote &&
      row.source_url &&
      ["company_website", "conference_flyer"].includes(row.evidence_source),
  ),
);
assert.equal(profiles.length, 28);
assert.ok(profiles.filter((row) => Number(row.pages_crawled) > 0).length >= 27);
assert.ok(sources.length >= 60);
assert.ok(sources.every((row) => /^[a-f0-9]{64}$/.test(row.content_sha256)));

const flyerCompanies = new Set(
  documents.map((row) => row.exhibitor_id),
);
assert.deepEqual(
  [...flyerCompanies].sort(),
  ["barndoor", "c1", "merge", "omnitrust", "promptql"],
);

for (const document of documents) {
  await access(path.join(dataDir, "raw", document.source_file));
  await access(path.join(dataDir, "extracted", document.extracted_markdown));
}

await access(
  path.join(
    root,
    "outputs",
    "01a1d559-faf8-71f0-b349-e7d66663b9ea",
    "Generative_AI_Summit_Boston_2026_exhibitors.xlsx",
  ),
);

console.log(
  `Conference data valid: ${speakers.length} speaker records, ` +
    `${capabilities.length} capability claims, ${sessions.length} agenda entries.`,
);

import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import {
  CONFERENCE_DATA_MOUNT,
  CONFERENCE_DOCUMENTS_CSV,
  CONFERENCE_WORKBOOK_FILENAME,
} from "./conference-config";

const CONFERENCE_DIR = path.join(process.cwd(), "data", "conference");
const EXTRACTED_DIR = path.join(CONFERENCE_DIR, "extracted");
const RAW_DIR = path.join(CONFERENCE_DIR, "raw");
const WORKBOOK_PATH = path.join(
  process.cwd(),
  "outputs",
  "01a1d559-faf8-71f0-b349-e7d66663b9ea",
  CONFERENCE_WORKBOOK_FILENAME,
);

export type ConferenceDocument = {
  exhibitor_id: string;
  exhibitor_name: string;
  doc_id: string;
  source_file: string;
  page_count: number;
  extracted_markdown: string;
};

function parseCsv(text: string): Array<Record<string, string>> {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;

  for (let i = 0; i < text.length; i++) {
    const char = text[i]!;
    if (char === '"') {
      if (quoted && text[i + 1] === '"') {
        field += '"';
        i++;
      } else {
        quoted = !quoted;
      }
    } else if (char === "," && !quoted) {
      row.push(field);
      field = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      if (row.some((value) => value.length > 0)) rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }

  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }

  const [headers, ...body] = rows;
  if (!headers) return [];
  return body.map((values) =>
    Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""])),
  );
}

export async function loadConferenceDocuments(): Promise<ConferenceDocument[]> {
  const text = await readFile(path.join(CONFERENCE_DIR, CONFERENCE_DOCUMENTS_CSV), "utf8");
  return parseCsv(text).map((row) => ({
    exhibitor_id: row.exhibitor_id,
    exhibitor_name: row.exhibitor_name,
    doc_id: row.doc_id,
    source_file: row.source_file,
    page_count: Number(row.page_count),
    extracted_markdown: row.extracted_markdown,
  }));
}

export async function getConferenceSourcePath(docId: string): Promise<string | null> {
  const documents = await loadConferenceDocuments();
  const document = documents.find((item) => item.doc_id === docId);
  if (!document) return null;
  const sourcePath = path.resolve(RAW_DIR, document.source_file);
  if (!sourcePath.startsWith(`${path.resolve(RAW_DIR)}${path.sep}`)) return null;
  return sourcePath;
}

export async function getConferenceWorkbook(): Promise<{
  filename: string;
  bytes: Uint8Array;
}> {
  return {
    filename: CONFERENCE_WORKBOOK_FILENAME,
    bytes: await readFile(WORKBOOK_PATH),
  };
}

export async function seedConferenceFiles(): Promise<
  Array<{ file: File; mountPath: string }>
> {
  const extractedFiles = (await readdir(EXTRACTED_DIR))
    .filter((name) => name.endsWith(".md"))
    .sort();
  const files: Array<{ file: File; mountPath: string }> = [];

  const add = async (
    sourcePath: string,
    filename: string,
    mountPath: string,
    type: string,
  ) => {
    const bytes = await readFile(sourcePath);
    files.push({
      file: new File([bytes], filename, { type }),
      mountPath,
    });
  };

  await add(
    path.join(CONFERENCE_DIR, "exhibitors.csv"),
    "exhibitors.csv",
    `${CONFERENCE_DATA_MOUNT}/exhibitors.csv`,
    "text/csv",
  );
  await add(
    path.join(CONFERENCE_DIR, CONFERENCE_DOCUMENTS_CSV),
    CONFERENCE_DOCUMENTS_CSV,
    `${CONFERENCE_DATA_MOUNT}/${CONFERENCE_DOCUMENTS_CSV}`,
    "text/csv",
  );
  await add(
    WORKBOOK_PATH,
    CONFERENCE_WORKBOOK_FILENAME,
    `${CONFERENCE_DATA_MOUNT}/${CONFERENCE_WORKBOOK_FILENAME}`,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  );

  for (const [filename, type] of [
    ["company_profiles.csv", "text/csv"],
    ["company_sources.csv", "text/csv"],
    ["capabilities.csv", "text/csv"],
    ["sessions.csv", "text/csv"],
    ["speakers.csv", "text/csv"],
    ["speaker_sessions.csv", "text/csv"],
    ["company_site_text.md", "text/markdown"],
  ] as const) {
    await add(
      path.join(CONFERENCE_DIR, filename),
      filename,
      `${CONFERENCE_DATA_MOUNT}/${filename}`,
      type,
    );
  }

  for (const filename of extractedFiles) {
    await add(
      path.join(EXTRACTED_DIR, filename),
      filename,
      `${CONFERENCE_DATA_MOUNT}/flyers/${filename}`,
      "text/markdown",
    );
  }

  return files;
}

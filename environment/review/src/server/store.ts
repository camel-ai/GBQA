import Database from "better-sqlite3";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import type { ImportPayload, ReviewPayload } from "./types.js";

const dbPath = join(process.cwd(), "data", "review.sqlite");
mkdirSync(dirname(dbPath), { recursive: true });

export const db = new Database(dbPath);

db.exec(`
CREATE TABLE IF NOT EXISTS candidates (
  id TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  verification TEXT,
  review TEXT,
  review_status TEXT DEFAULT 'unreviewed'
);
`);

export function importRun(payload: ImportPayload) {
  const ranked = readJsonl(join(payload.runDir, "ranked.jsonl"));
  const verified = new Map(
    readJsonl(join(payload.runDir, "verified.jsonl")).map((row) => [row.candidate_id, row]),
  );
  const insert = db.prepare(`
    INSERT INTO candidates (id, payload, verification)
    VALUES (@id, @payload, @verification)
    ON CONFLICT(id) DO UPDATE SET
      payload = excluded.payload,
      verification = excluded.verification
  `);
  const transaction = db.transaction(() => {
    for (const row of ranked) {
      insert.run({
        id: row.candidate_id,
        payload: JSON.stringify(row),
        verification: JSON.stringify(verified.get(row.candidate_id) ?? null),
      });
    }
  });
  transaction();
  return { imported: ranked.length };
}

export function listCandidates() {
  return db
    .prepare("SELECT id, payload, verification, review, review_status FROM candidates ORDER BY id")
    .all()
    .map(normalizeRow);
}

export function getCandidate(id: string) {
  const row = db
    .prepare("SELECT id, payload, verification, review, review_status FROM candidates WHERE id = ?")
    .get(id);
  return row ? normalizeRow(row) : null;
}

export function saveReview(id: string, payload: ReviewPayload) {
  const review = {
    ...payload,
    reviewedAt: new Date().toISOString(),
  };
  db.prepare(
    "UPDATE candidates SET review = ?, review_status = ? WHERE id = ?",
  ).run(JSON.stringify(review), payload.status, id);
  return getCandidate(id);
}

export function exportApproved(runDir: string) {
  const rows = db
    .prepare("SELECT id, payload, verification, review FROM candidates WHERE review_status = 'accepted'")
    .all()
    .map(normalizeRow)
    .filter((row) => row.review?.approvedForExport !== false);
  const seeds = rows.map(toTaskSeed);
  const outputPath = join(runDir, "approved_task_seeds.jsonl");
  writeFileSync(outputPath, seeds.map((seed) => JSON.stringify(seed)).join("\n") + "\n", "utf-8");
  return { exported: seeds.length, outputPath };
}

function normalizeRow(row: any) {
  return {
    id: String(row.id),
    payload: JSON.parse(row.payload),
    verification: row.verification ? JSON.parse(row.verification) : null,
    review: row.review ? JSON.parse(row.review) : null,
    reviewStatus: row.review_status,
  };
}

function readJsonl(path: string) {
  try {
    return readFileSync(path, "utf-8")
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line));
  } catch {
    return [];
  }
}

function toTaskSeed(row: any) {
  const candidate = row.payload;
  const repo = candidate.repository;
  const releasePair = candidate.release_pair;
  const review = row.review ?? {};
  const slug = candidate.candidate_id;
  return {
    task_id: `gbqa/${slug}`,
    slug,
    benchmark_status: review.benchmarkStatus ?? "draft",
    repository: repo.html_url,
    baseline_release: releasePair?.baseline_release ?? "",
    fixed_release: releasePair?.fixed_release ?? "",
    baseline_archive_url: releasePair?.baseline_archive_url ?? "",
    interaction_modes: candidate.tags?.interaction ?? [candidate.kind],
    primary_interaction_mode: review.primaryInteractionMode ?? candidate.kind,
    service: {
      host: "127.0.0.1",
      port: 8000,
      health_path: "/health",
      api_base_path: "/api",
    },
    tags: review.tags ?? candidate.tags,
  };
}

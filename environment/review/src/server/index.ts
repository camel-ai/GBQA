import cors from "@fastify/cors";
import Fastify from "fastify";
import { exportApproved, getCandidate, importRun, listCandidates, saveReview } from "./store.js";
import type { ImportPayload, ReviewPayload } from "./types.js";

const app = Fastify({ logger: true });
await app.register(cors, { origin: true });

app.post<{ Body: ImportPayload }>("/api/import", async (request) => {
  return importRun(request.body);
});

app.get("/api/candidates", async () => {
  return listCandidates();
});

app.get<{ Params: { id: string } }>("/api/candidates/:id", async (request, reply) => {
  const candidate = getCandidate(request.params.id);
  if (!candidate) {
    reply.code(404);
    return { error: "candidate_not_found" };
  }
  return candidate;
});

app.post<{ Params: { id: string }; Body: ReviewPayload }>(
  "/api/candidates/:id/review",
  async (request, reply) => {
    const updated = saveReview(request.params.id, request.body);
    if (!updated) {
      reply.code(404);
      return { error: "candidate_not_found" };
    }
    return updated;
  },
);

app.post<{ Body: { runDir: string } }>("/api/export", async (request) => {
  return exportApproved(request.body.runDir);
});

const port = Number(process.env.PORT ?? 5174);
await app.listen({ host: "127.0.0.1", port });

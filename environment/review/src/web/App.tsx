import { useEffect, useState } from "react";

interface CandidateRow {
  id: string;
  payload: any;
  verification: any;
  review: any;
  reviewStatus: string;
}

export function App() {
  const [runDir, setRunDir] = useState("environment/catalog/runs/dev");
  const [candidates, setCandidates] = useState<CandidateRow[]>([]);
  const [selected, setSelected] = useState<CandidateRow | null>(null);

  async function refresh() {
    const response = await fetch("http://127.0.0.1:5174/api/candidates");
    setCandidates(await response.json());
  }

  async function importRun() {
    await fetch("http://127.0.0.1:5174/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ runDir }),
    });
    await refresh();
  }

  async function review(status: "accepted" | "rejected" | "needs_more_investigation") {
    if (!selected) return;
    const response = await fetch(`http://127.0.0.1:5174/api/candidates/${selected.id}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status,
        primaryInteractionMode: selected.payload.kind,
        tags: selected.payload.tags,
        note: "",
        approvedForExport: status === "accepted",
      }),
    });
    setSelected(await response.json());
    await refresh();
  }

  async function exportApproved() {
    await fetch("http://127.0.0.1:5174/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ runDir }),
    });
  }

  useEffect(() => {
    refresh().catch(() => setCandidates([]));
  }, []);

  return (
    <main className="shell">
      <section className="toolbar">
        <div>
          <h1>GBQA Environment Review</h1>
          <p>Inspect verified GitHub environments before exporting benchmark tasks.</p>
        </div>
        <div className="controls">
          <input value={runDir} onChange={(event) => setRunDir(event.target.value)} />
          <button onClick={importRun}>Import Run</button>
          <button onClick={exportApproved}>Export Approved</button>
        </div>
      </section>
      <section className="grid">
        <aside className="list">
          {candidates.map((candidate) => (
            <button
              key={candidate.id}
              className={candidate.id === selected?.id ? "selected" : ""}
              onClick={() => setSelected(candidate)}
            >
              <strong>{candidate.id}</strong>
              <span>{candidate.payload.kind} / {candidate.reviewStatus}</span>
            </button>
          ))}
        </aside>
        <article className="detail">
          {selected ? (
            <>
              <h2>{selected.payload.name}</h2>
              <a href={selected.payload.repository.html_url} target="_blank" rel="noreferrer">
                {selected.payload.repository.full_name}
              </a>
              <div className="score">
                Score: {selected.payload.score?.total ?? "n/a"} | Verification:{" "}
                {selected.verification?.status ?? "not run"}
              </div>
              <pre>{JSON.stringify(selected.payload, null, 2)}</pre>
              {selected.verification && <pre>{JSON.stringify(selected.verification, null, 2)}</pre>}
              <div className="actions">
                <button onClick={() => review("accepted")}>Accept</button>
                <button onClick={() => review("needs_more_investigation")}>Needs Investigation</button>
                <button onClick={() => review("rejected")}>Reject</button>
              </div>
            </>
          ) : (
            <p>Select a candidate to review.</p>
          )}
        </article>
      </section>
    </main>
  );
}

import { loadRuns } from "../../lib/runs";

const GEMINI_MODEL = process.env.GEMINI_MODEL || "gemini-2.5-flash";

function summarizeRuns(runs) {
  if (runs.length === 0) return "No agent runs have been logged yet.";
  return runs
    .map(
      (r) =>
        `${r.created_at} | ${r.disease}/${r.region}/${r.metric} | value=${r.value} baseline_mean=${r.baseline_mean} z=${r.z_score} | ` +
        `${r.flagged ? "FLAGGED" : "not flagged"} (confidence: ${r.confidence}) | reasoning: ${r.reasoning}` +
        (r.reviewer_agree !== null && r.reviewer_agree !== undefined
          ? ` | second opinion (${r.reviewer_provider}): ${r.reviewer_agree ? "agrees" : "disagrees"} - ${r.reviewer_notes || ""}`
          : "")
    )
    .join("\n");
}

export async function POST(request) {
  const { question } = await request.json();
  if (!question || typeof question !== "string") {
    return Response.json({ error: "question is required" }, { status: 400 });
  }

  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    return Response.json({ error: "GEMINI_API_KEY not configured" }, { status: 500 });
  }

  const runs = await loadRuns({ withUrls: false });
  const prompt =
    "You are answering questions about a dengue surveillance agent's past runs, using only the run log below. " +
    "If the log doesn't contain enough information to answer, say so plainly instead of guessing.\n\n" +
    `Run log (most recent first):\n${summarizeRuns(runs)}\n\nQuestion: ${question}`;

  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${apiKey}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] }),
    }
  );

  if (!res.ok) {
    return Response.json({ error: `Gemini request failed (${res.status})` }, { status: 502 });
  }

  const data = await res.json();
  const answer = data.candidates?.[0]?.content?.parts?.[0]?.text;
  if (!answer) {
    return Response.json({ error: "Gemini returned no answer" }, { status: 502 });
  }

  return Response.json({ answer });
}

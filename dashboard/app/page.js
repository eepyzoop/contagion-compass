import styles from "./page.module.css";
import { loadRuns } from "./lib/runs";
import QueryBox from "./QueryBox";

// Every run adds a new manifest in S3 -- never statically cache this page.
export const dynamic = "force-dynamic";

export default async function Home() {
  const runs = await loadRuns();

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <h1>Contagion Compass — surveillance runs</h1>
        <QueryBox />
        {runs.length === 0 && <p>No runs yet.</p>}
        <div className={styles.runList}>
          {runs.map((run) => (
            <article key={run.report_key} className={styles.card}>
              <div className={styles.cardHeader}>
                <span className={run.flagged ? styles.badgeFlagged : styles.badgeOk}>
                  {run.flagged ? "FLAGGED" : "Not flagged"}
                </span>
                <span>{run.disease} / {run.region} / {run.metric}</span>
                <span className={styles.muted}>{new Date(run.created_at).toLocaleString()}</span>
              </div>
              <p>
                Current: {run.value} &nbsp;|&nbsp; Baseline mean: {run.baseline_mean?.toFixed?.(1) ?? run.baseline_mean}
                &nbsp;|&nbsp; z-score: {run.z_score} &nbsp;|&nbsp; Confidence: {run.confidence}
              </p>
              <p>{run.reasoning}</p>
              {run.reviewer_agree !== undefined && run.reviewer_agree !== null && (
                <p className={styles.muted}>
                  Second opinion ({run.reviewer_provider}): {run.reviewer_agree ? "agrees" : "disagrees"}
                  {run.reviewer_notes ? ` — ${run.reviewer_notes}` : ""}
                </p>
              )}
              {run.chartUrl && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={run.chartUrl} alt="trend chart" className={styles.chart} />
              )}
              <p>
                {run.reportUrl && <a href={run.reportUrl}>Raw report</a>}
                {" "}
                <span className={styles.muted}>
                  via {run.llm_provider}, {run.tool_calls_made} tool call(s)
                </span>
              </p>
            </article>
          ))}
        </div>
      </main>
    </div>
  );
}

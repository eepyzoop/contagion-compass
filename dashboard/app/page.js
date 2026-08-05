import { S3Client, ListObjectsV2Command, GetObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import styles from "./page.module.css";

// Every run adds a new manifest in S3 -- never statically cache this page.
export const dynamic = "force-dynamic";

const BUCKET = process.env.S3_BUCKET;
const client = new S3Client({ region: process.env.AWS_REGION || "us-east-1" });

async function streamToString(stream) {
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf-8");
}

async function loadRuns() {
  const list = await client.send(
    new ListObjectsV2Command({ Bucket: BUCKET, Prefix: "reports/" })
  );
  const jsonKeys = (list.Contents || [])
    .map((o) => o.Key)
    .filter((k) => k.endsWith(".json"));

  const runs = await Promise.all(
    jsonKeys.map(async (key) => {
      const obj = await client.send(new GetObjectCommand({ Bucket: BUCKET, Key: key }));
      const manifest = JSON.parse(await streamToString(obj.Body));

      const [reportUrl, chartUrl] = await Promise.all([
        manifest.report_key
          ? getSignedUrl(client, new GetObjectCommand({ Bucket: BUCKET, Key: manifest.report_key }), {
              expiresIn: 3600,
            })
          : null,
        manifest.chart_key
          ? getSignedUrl(client, new GetObjectCommand({ Bucket: BUCKET, Key: manifest.chart_key }), {
              expiresIn: 3600,
            })
          : null,
      ]);

      return { ...manifest, reportUrl, chartUrl };
    })
  );

  return runs.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
}

export default async function Home() {
  const runs = await loadRuns();

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <h1>Contagion Compass — surveillance runs</h1>
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

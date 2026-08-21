import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

// Phase 7: structured run data comes from the /runs API (Neon-backed),
// not S3 manifests -- see the 2026-08-21 dashboard-data-source decision.
// Report/chart files still live on S3, so this still presigns those keys.
const BUCKET = process.env.S3_BUCKET;
const API_BASE_URL = process.env.API_BASE_URL;
const client = new S3Client({ region: process.env.AWS_REGION || "us-east-1" });

function presign(key) {
  if (!key) return null;
  return getSignedUrl(client, new GetObjectCommand({ Bucket: BUCKET, Key: key }), { expiresIn: 3600 });
}

// Every run adds a new decision_log row -- always re-fetch, never cache across requests.
export async function loadRuns({ withUrls = true, limit = 50 } = {}) {
  const res = await fetch(`${API_BASE_URL}/runs?limit=${limit}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load runs from API (${res.status})`);
  const { runs } = await res.json();

  if (!withUrls) return runs;

  return Promise.all(
    runs.map(async (run) => {
      const [reportUrl, reportUrlPublic, chartUrl] = await Promise.all([
        presign(run.report_key),
        presign(run.report_key_public),
        presign(run.chart_key),
      ]);
      return { ...run, reportUrl, reportUrlPublic, chartUrl };
    })
  );
}

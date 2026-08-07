import { S3Client, ListObjectsV2Command, GetObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

const BUCKET = process.env.S3_BUCKET;
const client = new S3Client({ region: process.env.AWS_REGION || "us-east-1" });

async function streamToString(stream) {
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf-8");
}

// Every run adds a new manifest in S3 -- always re-list, never cache across requests.
export async function loadRuns({ withUrls = true } = {}) {
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
      if (!withUrls) return manifest;

      const [reportUrl, reportUrlPublic, chartUrl] = await Promise.all([
        manifest.report_key
          ? getSignedUrl(client, new GetObjectCommand({ Bucket: BUCKET, Key: manifest.report_key }), {
              expiresIn: 3600,
            })
          : null,
        manifest.report_key_public
          ? getSignedUrl(client, new GetObjectCommand({ Bucket: BUCKET, Key: manifest.report_key_public }), {
              expiresIn: 3600,
            })
          : null,
        manifest.chart_key
          ? getSignedUrl(client, new GetObjectCommand({ Bucket: BUCKET, Key: manifest.chart_key }), {
              expiresIn: 3600,
            })
          : null,
      ]);

      return { ...manifest, reportUrl, reportUrlPublic, chartUrl };
    })
  );

  return runs.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
}

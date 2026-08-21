// Phase 7 task 3: client-side Sentry. Needs the NEXT_PUBLIC_ prefix to reach
// the browser bundle; blank means skipped, same pattern as the server side.
import * as Sentry from "@sentry/nextjs";

if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
  Sentry.init({
    dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
    tracesSampleRate: 0,
  });
}

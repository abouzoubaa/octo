#!/usr/bin/env bash
# Database backup → S3-compatible storage. Run from cron (e.g. daily).
# Restore: gunzip -c sift-YYYY-MM-DD.sql.gz | psql "$CCI_DATABASE_URL"
#
# Required env: CCI_DATABASE_URL, BACKUP_BUCKET (s3://...), and AWS creds or
# an mc alias for MinIO. Keeps the last RETAIN_DAYS days.
set -euo pipefail

RETAIN_DAYS="${RETAIN_DAYS:-14}"
STAMP="$(date -u +%Y-%m-%dT%H%M%SZ)"
OUT="/tmp/sift-${STAMP}.sql.gz"

echo "[backup] dumping database…"
pg_dump "${CCI_DATABASE_URL#*+psycopg://}" | gzip > "$OUT" \
  || pg_dump "$CCI_DATABASE_URL" | gzip > "$OUT"

echo "[backup] uploading to ${BACKUP_BUCKET}…"
aws s3 cp "$OUT" "${BACKUP_BUCKET}/sift-${STAMP}.sql.gz"

echo "[backup] pruning backups older than ${RETAIN_DAYS} days…"
CUTOFF="$(date -u -d "-${RETAIN_DAYS} days" +%Y-%m-%d 2>/dev/null || date -u -v-"${RETAIN_DAYS}"d +%Y-%m-%d)"
aws s3 ls "${BACKUP_BUCKET}/" | awk '{print $4}' | while read -r f; do
  d="$(echo "$f" | sed -E 's/sift-([0-9-]+)T.*/\1/')"
  [ "$d" \< "$CUTOFF" ] && aws s3 rm "${BACKUP_BUCKET}/${f}" || true
done

rm -f "$OUT"
echo "[backup] done: sift-${STAMP}.sql.gz"

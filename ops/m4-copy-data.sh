#!/usr/bin/env bash
# M4: copy the VM database's data into Cloud SQL, then print exact row counts for both.
#
# Run ON the VM (it is the only host that can reach both databases):
#   CLOUDSQL_URL='postgresql://occdesk:<password>@<private-ip>:5432/occdesk' ops/m4-copy-data.sh
#
# Order: run `alembic upgrade head` against Cloud SQL first (it creates the tables and inserts
# linkage_weights itself). Do NOT run the seed scripts: hazard_categories and users are copied
# from the old database so ids stay identical to the ones report_hazards points at. It reads
# from the old database and writes to the new one; the old database is not modified.
set -euo pipefail

: "${CLOUDSQL_URL:?set CLOUDSQL_URL (plain postgresql:// form)}"
OLD="${OLD_DB_CONTAINER:-occurrence-desk-db-1}"
IMAGE="${PSQL_IMAGE:-postgres:16-bookworm}"
# Parents before children, so foreign keys hold while loading.
TABLES=(hazard_categories users documents ingest_events reports report_fields report_hazards)

new_psql() { sudo docker run --rm -i "$IMAGE" psql "$CLOUDSQL_URL" -v ON_ERROR_STOP=1 "$@"; }
old_psql() { sudo docker exec -i "$OLD" psql -U occdesk -d occdesk -v ON_ERROR_STOP=1 "$@"; }

counts() {
  for t in aircraft airports carriers dispositions documents flights hazard_categories \
    ingest_events linkage_weights report_fields report_flight_links report_hazards reports users; do
    printf '%s %s\n' "$t" "$("$1" -At -c "SELECT count(*) FROM $t")"
  done
}

echo "Copying: ${TABLES[*]}"
ARGS=()
for t in "${TABLES[@]}"; do ARGS+=(--table="$t"); done
sudo docker exec "$OLD" pg_dump -U occdesk -d occdesk --data-only --disable-triggers \
  "${ARGS[@]}" | new_psql -q

echo "--- sequences"
# Keep id sequences ahead of the copied rows so the next insert does not collide.
new_psql -At -c "
SELECT setval(pg_get_serial_sequence(format('%I', t), 'id'), GREATEST(max_id, 1))
FROM (VALUES ('hazard_categories', (SELECT coalesce(max(id),0) FROM hazard_categories)),
             ('users', (SELECT coalesce(max(id),0) FROM users)),
             ('documents', (SELECT coalesce(max(id),0) FROM documents)),
             ('ingest_events', (SELECT coalesce(max(id),0) FROM ingest_events)),
             ('reports', (SELECT coalesce(max(id),0) FROM reports))
     ) AS v(t, max_id)
WHERE pg_get_serial_sequence(format('%I', t), 'id') IS NOT NULL;" >/dev/null

echo "--- exact counts: old | new"
paste -d'|' <(counts old_psql) <(counts new_psql)

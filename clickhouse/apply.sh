#!/usr/bin/env bash
# Primijeni shemu i korisnike. Idempotentno.
#
# Pokreće se na dva načina:
#  1. ClickHouse entrypoint ga sam izvrši na PRVOM startu (prazan volume),
#     jer je montiran u /docker-entrypoint-initdb.d/.
#  2. `scripts/ch-apply.sh` ga vrti kroz `docker exec` nakon promjene SQL-a.
#
# Lozinke dolaze iz okoline kontejnera (Coolify env), nikad iz gita.
set -euo pipefail

: "${CLICKHOUSE_USER:?}" "${CLICKHOUSE_PASSWORD:?}"
: "${CH_INGEST_PASSWORD:?postavi CH_INGEST_PASSWORD}" "${CH_READER_PASSWORD:?postavi CH_READER_PASSWORD}"

ch() { clickhouse client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery "$@"; }

for f in /analytics/sql/*.sql; do
  echo "apply: $f"
  ch < "$f"
done

# Lozinke idu kroz --param_, ne kroz interpolaciju u SQL string.
ch --param_ingest="$CH_INGEST_PASSWORD" --param_reader="$CH_READER_PASSWORD" <<'SQL'
CREATE SETTINGS PROFILE IF NOT EXISTS ingest_profile SETTINGS
    async_insert = 1,
    wait_for_async_insert = 1,
    async_insert_busy_timeout_max_ms = 1000,
    max_insert_threads = 2;

CREATE SETTINGS PROFILE IF NOT EXISTS reader_profile SETTINGS
    readonly = 2,
    max_execution_time = 60,
    max_memory_usage = 2000000000,
    max_result_rows = 1000000;

CREATE USER IF NOT EXISTS ingest IDENTIFIED WITH sha256_password BY {ingest:String}
    SETTINGS PROFILE 'ingest_profile';
ALTER USER ingest IDENTIFIED WITH sha256_password BY {ingest:String};
GRANT INSERT ON analytics.events TO ingest;

CREATE USER IF NOT EXISTS reader IDENTIFIED WITH sha256_password BY {reader:String}
    SETTINGS PROFILE 'reader_profile';
ALTER USER reader IDENTIFIED WITH sha256_password BY {reader:String};
GRANT SELECT ON analytics.* TO reader;
SQL
echo "apply: gotovo"

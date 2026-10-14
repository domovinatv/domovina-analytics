#!/usr/bin/env bash
# Primijeni clickhouse/sql/*.sql i korisnike na produkcijskom ClickHouseu.
#
# SQL datoteke su ugrađene u image, pa redoslijed mora biti:
# git push → Coolify Redeploy → ovaj skript. (Entrypoint ih sam izvrši SAMO
# na praznom volumenu, tj. pri prvom deployu.)
#
# Usage: ./scripts/ch-apply.sh            # nađe kontejner po imageu
#        CH_CONTAINER=<ime> ./scripts/ch-apply.sh
set -euo pipefail
SSH_KEY="${SSH_KEY:-$HOME/.ssh/dom-001-oracle-ssh-key-2026-04-20.key}"
HOST="${HOST:-ubuntu@89.168.100.120}"

# Na istom serveru je i ClickHouse od domovina-rag (24.10). Naš je image
# lokalni build (Coolify ga imenuje po resursu), pa se traži po okolini:
# jedini nosi CH_INGEST_PASSWORD i apply.sh.
ssh -i "$SSH_KEY" "$HOST" CH_CONTAINER="${CH_CONTAINER:-}" 'bash -s' <<'REMOTE'
set -euo pipefail
c="$CH_CONTAINER"
if [ -z "$c" ]; then
  for id in $(docker ps -q); do
    if docker exec "$id" sh -c 'test -n "$CH_INGEST_PASSWORD" && test -x /docker-entrypoint-initdb.d/apply.sh' 2>/dev/null; then c="$id"; break; fi
  done
fi
[ -n "$c" ] || { echo "Nisam našao analytics ClickHouse kontejner" >&2; exit 2; }
echo "→ $(docker inspect -f '{{.Name}}' "$c")"
docker exec "$c" /docker-entrypoint-initdb.d/apply.sh
REMOTE

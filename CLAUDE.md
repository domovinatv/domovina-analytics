# CLAUDE.md — domovina-analytics

Ingest Worker (`src/`) + ClickHouse i Grafana na Coolifyju (`docker-compose.yml`).
Klijent je `domovina.ai/packages/podcast_core/lib/services/analytics/`.
Slika, odluke i lokalni rad: `README.md`. Ugovor: `docs/ugovor.md`.

- `npm test` + `npx tsc --noEmit` prije commita.
- **Rule (jedan loš redak obara cijeli insert)**: sve što ide u tipizirani
  stupac (UUID, broj) `src/validate.ts` popravi ili odbaci. 400 iz
  ClickHousea ne ide u Queue (ponovni pokušaj ga ne popravi).
- **Rule (putanja na tri mjesta)**: `routes` + `INGEST_PATH` u
  `wrangler.jsonc` i `Endpoints.events` u `podcast_core`. Bez riječi s
  adblock popisa (`analytics`, `track`, `collect`, `event`, `beacon`, `pixel`).
- **Rule (Queue je rezerva)**: glavni put je izravan insert; ne prebacivati
  sve kroz Queue bez pogleda u `docs/troskovi.md`.
- Shema: `clickhouse/sql/*.sql` idempotentni; produkcija kroz
  `scripts/ch-apply.sh` NAKON Coolify redeploya.
- Na serveru je i ClickHouse od `domovina-rag` (24.10) — naš je 25.8. Nikad
  ne miješati kontejnere ni volumene.

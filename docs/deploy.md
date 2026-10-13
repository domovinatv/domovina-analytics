# Deploy

Redoslijed je bitan: **backend prije klijenta**. Klijent koji šalje na
`/api/state` prije nego Worker postoji ne radi štetu (Pages vrati grešku pa
klijent batch baci), ali ništa se ne broji.

## 1. Coolify: ClickHouse + Grafana

Obrazac kao `sms.domovina.ai` i `domovina-cutter` (Docker Compose resurs nad
GitHub repoom).

- Resurs: **Docker Compose**, repo `domovinatv/domovina-analytics`, grana
  `main`, compose path `/docker-compose.yml`.
- Env (sve osim zadnjeg označi kao **Secret**; generiraj s `openssl rand -hex 24`):
  `CH_ADMIN_PASSWORD`, `CH_INGEST_PASSWORD`, `CH_READER_PASSWORD`,
  `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_ROOT_URL=https://analitika.domovina.ai`.
- Domene servisa: `clickhouse` → `https://ch-ingest.domovina.ai:8123`,
  `grafana` → `https://analitika.domovina.ai:3000`.
- **Deploy.** Env se aktivira samo kroz Redeploy, ne kroz Restart.
- Provjera na serveru: entrypoint je izvršio `apply.sh`.

  ```bash
  ssh -i ~/.ssh/dom-001-oracle-ssh-key-2026-04-20.key ubuntu@89.168.100.120 \
    "docker ps --format '{{.Names}} {{.Image}} {{.Status}}' | grep -E 'clickhouse-server:25|grafana'"
  ```

## 2. Cloudflare Tunnel + Access

Postojeći tunel (`01a25a60-…`) → Public Hostnames, isti obrazac kao
`search.domovina.ai`. cloudflared prema Traefiku ide preko HTTP-a, ne HTTPS-a.

| hostname | service |
|---|---|
| `ch-ingest.domovina.ai` | `http://traefik:80` |
| `analitika.domovina.ai` | `http://traefik:80` |

Zero Trust → Access → Applications:

- **`ch-ingest.domovina.ai`**: policy *Service Auth* sa service tokenom
  `domovina-analytics-worker`. Client ID i Secret idu u Worker (korak 3).
  Bez tokena ClickHouse HTTP nije dostupan s interneta, čak ni uz lozinku.
- **`analitika.domovina.ai`**: policy *Allow* za tvoju e-poštu. Grafana
  login je drugi sloj.

## 3. Worker

```bash
npx wrangler queues create domovina-analytics-buffer
npx wrangler queues create domovina-analytics-dlq
npx wrangler secret put CH_PASSWORD               # = CH_INGEST_PASSWORD
npx wrangler secret put CF_ACCESS_CLIENT_ID
npx wrangler secret put CF_ACCESS_CLIENT_SECRET
npx wrangler deploy
```

### Provjera: ima li route prednost pred Pages projektom

`domovina.ai` je custom domena Pages projekta `domovina-ai`. Worker route na
istom hostu mora uhvatiti `/api/state` prije Pagesa:

```bash
curl -si -X POST https://domovina.ai/api/state -A 'Mozilla/5.0' \
  -H 'Content-Type: text/plain' \
  --data '{"app":"domovina.ai","session_id":"deploy_probe","events":[{"n":"deploy_probe"}]}' | head -1
# očekivano: HTTP/2 204 (Pages bi vratio 200 s HTML-om ili 405)
```

Pa u ClickHouseu (Grafana → Explore):
`SELECT * FROM analytics.events WHERE event = 'deploy_probe'`.

Ako route **ne** hvata, rezerva je service binding iz `web/_worker.js` na
ovaj Worker, uz prosljeđivanje samo te putanje. To se zasad ne radi jer
dodaje vezu između repoa.

## 4. Ograda troškova

Cloudflare dashboard → **Notifications** → *Usage Based Billing*: prag 20 $.
Bug koji šalje previše vidi se isti dan, ne na računu (`docs/troskovi.md`).

## 5. Klijent

U `domovina.ai`: `Endpoints.events` je već postavljen u
`packages/podcast_core/lib/brand/domovina_brand.dart`, a klijent je na `main`
od `d9b35db`. Deploy weba (`./scripts/deploy.sh` s `main`) i sljedeći nightly za iOS i Android.

Dok ovaj Worker ne postoji, produkcija na `POST /api/state` vraća **200 s
HTML-om** (SPA fallback u `web/_worker.js`). Klijent to čita kao uspjeh i
batch baci: nema štete ni ponavljanja, ali se ništa ne broji (izmjereno 14. 10. 2026.).

**Otvoreno prije produkcije: politika privatnosti.** Odluka je „praćenje
svima od prvog pokretanja, opisano u politici privatnosti” (`user_id` +
trajni `device_id`, bez consent bannera), ali pravni tekst u aplikaciji
to još ne spominje.

Provjera u **Braveu sa Shields uključenim**: DevTools → Network →
`api/state` mora imati status 204, a ne `(blocked:other)`.

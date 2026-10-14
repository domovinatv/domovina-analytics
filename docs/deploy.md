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
- Domene servisa: `clickhouse` → `http://ch-ingest.domovina.ai:8123`,
  `grafana` → `http://analitika.domovina.ai:3000`. **`http://`, ne
  `https://`**, kao `search.domovina.ai`: TLS završava na Cloudflareu, a uz
  `https://` Traefik na portu 80 vraća redirect na isti URL.
- Datoteke iz repoa su ugrađene u image (`build:` u composeu). Coolify za
  Compose resurs ne kopira repo na host, pa je bind mount `./clickhouse/apply.sh`
  u kontejneru bio prazna mapa (`apply.sh: Is a directory`, 14. 10. 2026.).
- **Deploy.** Env se aktivira samo kroz Redeploy, ne kroz Restart.
- Nakon deploya **uvijek** `./scripts/ch-apply.sh`: entrypoint izvrši
  `apply.sh` samo na praznom volumenu, a idempotentan je.
- Lozinke su u `.local-secrets.env` (gitignored), uz `COOLIFY_APP_UUID`.
  Coolify API ih vraća prazne (token nema `read:sensitive`), pa se provjerava
  prijava u kontejneru, ne API.
- Provjera na serveru:

  ```bash
  ssh -i ~/.ssh/dom-001-oracle-ssh-key-2026-04-20.key ubuntu@89.168.100.120 \
    "docker ps --format '{{.Names}} {{.Image}} {{.Status}}' | grep -E 'clickhouse-server:25|grafana'"
  ```

## 2. Cloudflare Tunnel + Access

**Redoslijed: Access prije hostnamea**, inače je ClickHouse HTTP na tren
javan. Postojeći tunel `domovina-001-coolify-oracle` (`01a25a60-…`), isti
obrazac kao ostali hostovi u njemu, uz proxied CNAME na
`01a25a60-….cfargotunnel.com`:

| hostname | service |
|---|---|
| `ch-ingest.domovina.ai` | `http://localhost:80` |
| `analitika.domovina.ai` | `http://localhost:80` |

Zero Trust → Access → Applications:

- **`ch-ingest.domovina.ai`**: policy *Service Auth* sa service tokenom
  `domovina-analytics-worker` (trajanje `forever`: istekao token bi tiho
  slao sve u Queue pa u DLQ). Client ID i Secret idu izravno u Worker
  secrets i nisu nigdje drugdje zapisani; za rotaciju napravi novi token.
  Bez tokena ClickHouse HTTP vraća 403, čak ni uz lozinku.
- **`analitika.domovina.ai`**: policy *Allow* za `stepanic.matija@gmail.com`
  i `ms@ff.hr`. Grafana login je drugi sloj.

Stanje 14. 10. 2026.: oboje napravljeno kroz dashboard API (Cloudflare token
iz `domovina-rag` ne vidi tunele ni Access).

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

**Izmjereno 14. 10. 2026.: route hvata.** Probe je vratio 204 i red
`deploy_probe` je sjeo u ClickHouse, a `GET /` i dalje servira Pages. Service
binding iz `web/_worker.js` ne treba.

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

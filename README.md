# domovina-analytics

Vlastita analitika događaja za DOMOVINA proizvode. Nema Google Analyticsa,
Amplitudea ni Segmenta. Podaci su u našem ClickHouseu, odvojeno od Supabasea.

```
Flutter (web, iOS, Android, TV)                      klijent: domovina.ai/packages/podcast_core
  │  batch svakih 30 s u prednjem planu (= heartbeat), završni flush pri odlasku
  ▼
POST https://domovina.ai/api/state                   Worker route, ISTI origin kao aplikacija
  │  validacija, geo iz request.cf, UA → preglednik/OS, IP se ne sprema
  │  204 odmah; zapis u pozadini (ctx.waitUntil)
  ├──► ClickHouse (Coolify) INSERT async_insert ───── uspjeh: gotovo
  └──► ne uspije? → Queue domovina-analytics-buffer → consumer ponavlja → DLQ nakon 5
                                                       │
Grafana (Coolify) ◄── korisnik `reader`, read-only ────┘
```

| dokument | sadržaj |
|---|---|
| [`docs/ugovor.md`](docs/ugovor.md) | omotnica, pravila polja, odgovori, popis događaja |
| [`docs/deploy.md`](docs/deploy.md) | Coolify, Tunnel, Access, Worker; redoslijed i provjere |
| [`docs/troskovi.md`](docs/troskovi.md) | cijene Cloudflarea, izračun po broju korisnika, ograde |
| [`docs/upiti.md`](docs/upiti.md) | gotovi SQL upiti (online sada, korisnik, epizoda, zadržavanje) |
| [`docs/dashboardi.md`](docs/dashboardi.md) | Grafana dashboardi, što koji pokazuje, kako se mijenjaju |

## Odluke

- **Isti origin, neutralna putanja.** Adblockeri (Brave Shields, uBlock)
  blokiraju po popisima: tuđe domene i putanje s riječima `analytics`,
  `track`, `collect`, `beacon`, `pixel`, `telemetry`, `event`. Na
  `domovina.ai/api/state` nema ni jednog ni drugog. Flutter nema zasebnu
  tracking skriptu koja bi se dala blokirati po imenu datoteke. Repo je
  javan, pa se putanja može naći; ako je neki popis doda, mijenja se na
  tri mjesta (`wrangler.jsonc`: route i `INGEST_PATH`, te
  `Endpoints.events` u klijentu).
- **ClickHouse, jedna široka tablica.** Novi događaj ne traži migraciju
  (`event` + `props` JSON). Zaseban kontejner, a ne baza u ClickHouseu od
  `domovina-rag`, jer se rag compose redeploya stop-then-start i ne smije
  rušiti ingest.
- **Queue je rezerva, a ne glavni put.** Dok ClickHouse radi, Queue ne
  vidi ništa i ne košta ništa (`docs/troskovi.md`).
- **Korisnici u ClickHouseu:** `ingest` smije samo `INSERT` u
  `analytics.events`, `reader` samo `SELECT` (`readonly=2`, limiti), a
  `admin` je samo za `apply.sh`.

## Lokalno

```bash
cp .env.example .env            # popuni: openssl rand -hex 16
docker compose up -d --build    # ClickHouse :8123, Grafana :3000 (override = localhost portovi)
npm install
printf 'CH_URL=http://127.0.0.1:8123\nCH_PASSWORD=<CH_INGEST_PASSWORD>\n' > .dev.vars
npx wrangler dev --port 8787    # Worker + lokalni Queue
npm test                        # validacija i UA
```

Aplikacija protiv lokalnog Workera (iz `domovina.ai`):

```bash
flutter build web --wasm --profile \
  --dart-define=ANALYTICS_ENDPOINT=http://127.0.0.1:8787/api/state
```

U debug buildu je analitika ugašena; pali se s `--dart-define=ANALYTICS_IN_DEBUG=true`.

Izmjereno lokalno 14. 10. 2026.:
- Brave → Worker → ClickHouse donosi `session_start`, `screen_view` za `/`
  i za `/v/<id>` (s `video_id`) te `heartbeat` svakih 30 s.
- ClickHouse ugašen pri slanju: Worker vrati 204, batch ode u Queue i
  sjedne u bazu oko 30 s nakon ponovnog pokretanja.
- `ingest` ne može čitati, a `reader` ne može pisati (oba 500 iz
  ClickHousea).

## Promjena sheme

`clickhouse/sql/*.sql` su idempotentni. Na prvom startu ih izvrši entrypoint,
a kasnije `./scripts/ch-apply.sh` (SSH na server, `docker exec`).

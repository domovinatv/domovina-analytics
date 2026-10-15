# Ugovor: klijent → ingest

Jedini klijent danas je `podcast_core` u repou `domovina.ai`
(`packages/podcast_core/lib/services/analytics/`). Svaki budući klijent
(drugi proizvod, backend, skripta) šalje isto.

## Zahtjev

```
POST https://domovina.ai/api/state
Content-Type: text/plain        (web: bez CORS preflighta)  ili  application/json
```

Tijelo je **omotnica**: zajednička polja jednom, pa do 50 događaja.

```json
{
  "v": 1,
  "app": "domovina.ai",
  "device_id": "78164e13-526a-4d04-b29a-13dc9eb6817c",
  "session_id": "fd93b1fc-61a6-4785-a96d-57198f7358a5",
  "user_id": "3f2b8c1e-9a4d-4e2f-8b1a-0c9d8e7f6a5b",
  "platform": "web",
  "app_version": "2.0.186",
  "locale": "hr",
  "screen": [390, 844],
  "events": [
    { "id": "<uuid v4>", "t": 1791927355558, "n": "screen_view",
      "route": "/v/UM2MWlNUpqg", "video_id": "UM2MWlNUpqg" },
    { "id": "<uuid v4>", "t": 1791927385686, "n": "heartbeat", "route": "/v/UM2MWlNUpqg" }
  ]
}
```

| polje | pravilo | ako ne vrijedi |
|---|---|---|
| `app`, `session_id` | `[A-Za-z0-9_.:-]{1,64}` | 400, cijeli zahtjev |
| `device_id` | isto | prazno |
| `user_id` | UUID (Supabase `auth.users.id`) | prazno |
| `platform` | `web ios android tv macos windows linux` | `unknown` |
| `n` | `^[a-z][a-z0-9_]{1,63}$` | događaj odbačen |
| `id` | UUID | server generira novi |
| `t` | ms od epohe, ±7 dana od servera | vrijeme prijema |
| `props` | objekt, serijaliziran ≤ 4 KB | događaj odbačen |
| tijelo | ≤ 64 KB | 413 |

Server dodaje: `received_at`, `country`/`region`/`city` (Cloudflare),
`browser`/`os` (User-Agent). **IP se ne sprema.**

## Odgovori

| status | značenje | klijent |
|---|---|---|
| 204 | primljeno (ili prepoznat bot — namjerno isti odgovor) | gotovo |
| 400/413 | neispravan zahtjev | **ne šalji ponovno** |
| 403 | `Origin` nije na popisu | ne šalji ponovno |
| 429 | rate limit (20/min po uređaju) | ponovi kasnije |
| 5xx / mreža | | ponovi kasnije |

204 znači „Worker je preuzeo”, ne „sjelo je u ClickHouse”: zapis ide u
pozadini, uz Queue kao rezervu (README, „Tok podataka”).

## Događaji koje klijent danas šalje

| `n` | kada | posebno |
|---|---|---|
| `session_start` | prvi događaj sesije; nova sesija nakon 30 min neaktivnosti | `props.referrer`, `props.utm_*` (web) |
| `screen_view` | promjena lokacije rutera | `route` bez `/t/<sec>`; `video_id` za `/v`, `/m`, `/yt`; `channel` za `/c`; `props.person` za `/p` |
| `heartbeat` | otkucaj od 30 s u prednjem planu kad drugih događaja nema | temelj za „online sada” |
| `app_background` | odlazak u pozadinu / skriven tab | |
| `identify` / `sign_out` | promjena prijavljenog korisnika | |
| `sponsored_impression`, `sponsored_play_through`, `sponsored_click` | plaćeni sponzorski trenuci | `props.slot_key`, `brand`, `start`, `end` |
| `playback_start` | prvi `playing=true` nakon otvaranja epizode | `video_id`; `props.surface` (`v`/`m`/`tv`), `position_s`, `duration_s`, `wait_ms` (od otvaranja do zvuka) |
| `playback_pause` / `playback_resume` | promjena `playing` nakon starta | `position_s`; pauza nosi i kumulativni `listened_s` |
| `playback_seek` | ručni skok > 2 s; niz skokova (povlačenje slidera) javlja se jednom, 1,5 s nakon zadnjeg | `from_s`, `to_s`. Resume-seek u prvih 8 s nije skok |
| `playback_progress` | prag 10/25/50/75/90 % dosegnut **slušanjem** (preskočen skokom se ne javlja) | `pct`, `listened_s` |
| `playback_end` | zatvaranje epizode, ako je reprodukcija krenula | `listened_s`, `duration_s`, `end_pct`. Zatvoren tab ga ne pošalje — odslušano po (sesija, epizoda) je zato `max(listened_s)` preko pause/progress/end |
| `playback_rate` | promjena brzine | `from`, `to`; `route` nosi epizodu |
| `search` | zatvaranje palete pretrage s nepraznim upitom (jedan po otvaranju, ne po tipki) | `q` (≤ 100 znakova), `persons`/`channels`/`episodes` (broj prikazanih), `picked` (`person`/`channel`/`episode`/`moment`/`all_results`/`video_id`, prazno = ništa), `rank`; `video_id` otvorene epizode |
| `episode_find` | „Pronađi u epizodi": upit zatvoren brisanjem, novim upitom ili odlaskom s epizode | `q` (≤ 100), `hits`, `jumps` (koliko je puta skočeno iz rezultata) |

Novi događaj = `Analytics.instance.track('ime', props: {...})` u klijentu.
Shema se ne mijenja; dokumentiraj ga ovdje. Nova kategorija podatka (npr. slobodan
tekst kao `q`) mijenja i politiku privatnosti u `domovina.ai`
(`legalPrivacyAnalytics*`, `docs/compliance/`).

Reprodukciju računa `PlaybackAnalytics`
(`podcast_core/lib/services/analytics/playback_analytics.dart`) iz
`player.stream.playing` i `position`, pa hvata sve putanje (naše trake,
media_kitov tap, tipkovnica, lock screen).

## Kašnjenje do Grafane

Izmjereno 15. 10. 2026. nad 50 web događaja (v2.0.187), kao
`received_at − ts`:

| događaj | p50 | p90 | p99 |
|---|---|---|---|
| `screen_view` | 5,7 s | 22,8 s | 29,6 s |
| `session_start` | 5,4 s | 5,8 s | 5,8 s |
| `app_background` | 0,1 s | 0,8 s | 9,8 s |

Zbroj tri dijela: klijent drži red do 30 s (`Analytics.flushInterval`; prvi
batch nakon 5 s, `app_background` odmah), ClickHouse `async_insert` do ~1 s
(`async_insert_busy_timeout_max_ms`), Grafana osvježava svakih 10 s. Ukupno
obično 5–15 s, najviše ~40 s. „Online sada” gleda prozor od 90 s, pa korisnik
nestane do 90 s nakon odlaska.

Najjeftinija poluga je klijent: kraći `flushInterval` ili flush na
`screen_view` (`minFlushGap` 5 s štiti server). Cijena je 2–3× više zahtjeva;
rate limit 20/min po uređaju to i dalje pokriva.

Reprodukcija upita:

```sql
SELECT event, count() n,
  quantile(0.5)(dateDiff('millisecond', ts, received_at)) / 1000 AS p50_s,
  quantile(0.9)(dateDiff('millisecond', ts, received_at)) / 1000 AS p90_s
FROM analytics.events WHERE received_at > now() - INTERVAL 1 DAY
GROUP BY event ORDER BY n DESC;
```

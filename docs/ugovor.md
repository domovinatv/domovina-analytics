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

Novi događaj = `Analytics.instance.track('ime', props: {...})` u klijentu.
Shema se ne mijenja; dokumentiraj ga ovdje.

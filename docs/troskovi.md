# Troškovi

Cijene Cloudflarea (developers.cloudflare.com, provjereno 14. 10. 2026.), na
Workers Paid planu (5 $ mjesečno):

| | uključeno | preko toga |
|---|---|---|
| Workers zahtjevi | 10 M/mj | 0,30 $ po milijunu |
| Workers CPU | 30 M ms/mj | 0,02 $ po milijunu ms |
| Queues | 1 M operacija/mj | 0,40 $ po milijunu; poruka je oko 3 operacije (zapis, čitanje, brisanje) po 64 KB, a svaki retry je još jedno čitanje |

ClickHouse i Grafana su na postojećem Coolify VM-u, kao fiksni trošak koji
se već plaća.

## Izračun

Cijenu određuje broj **flusheva**, a ne broj događaja: jedan zahtjev nosi do
50 događaja (oko 10 KB). Pretpostavka je 15 min aktivnosti po korisniku dnevno
i flush svakih 30 s, dakle 30 zahtjeva po korisniku dnevno.

| dnevno aktivnih | zahtjeva/mj | Workers | Queue (samo kad CH ne radi) | ukupno |
|---|---|---|---|---|
| 1 000 | 0,9 M | 0 $ | ~0 $ | **5 $** |
| 10 000 | 9 M | 0 $ | ~0 $ | **5 $** |
| 100 000 | 90 M | 24 $ | ~0 $ | **~29 $** |

Queue bi kao glavni put pri 100 000 dnevno aktivnih stajao oko 108 $
mjesečno. Kao rezerva plaća se samo za vrijeme ispada ClickHousea.

## Ograde (sve su u kodu)

1. **Klijent**: flush najviše jednom u 30 s (prisilni flush samo pri
   odlasku u pozadinu, uz razmak od barem 5 s). Batch ≤ 50 događaja, red ≤ 500,
   u pozadini nema heartbeata. 4xx odgovor se ne šalje ponovno.
2. **Worker**: tijelo ≤ 64 KB, rate limit 20/min po uređaju ili IP-u (429),
   `Origin` allowlist, botovi dobiju 204 bez zapisa.
3. **Queue**: `max_retries: 5`, pa DLQ. Odgoda je 60 s, a za lošu poruku 300 s.
   400 iz ClickHousea (loš podatak) se ne stavlja u Queue nego ide u log.
4. **Cloudflare Notifications**: prag potrošnje (`docs/deploy.md` §4).

Rast je linearan s brojem korisnika. Eksponencijalni rast može izazvati samo
bug, a ograde 1–3 ga zaustavljaju.

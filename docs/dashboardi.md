# Dashboardi

https://analitika.domovina.ai (Cloudflare Access, pa Grafana login), mapa
**Analitika**. Svi dashboardi imaju tag `domovina` i u zaglavlju linkove
jedan na drugi.

| dashboard | uid | sadržaj |
|---|---|---|
| Pregled | `domovina-pregled` | online sada, danas, ekrani, epizode, izvori |
| Korisnici | `domovina-korisnici` | popis svih korisnika s brojkama; ulaz u profil |
| Korisnik | `domovina-korisnik` | profil jednog korisnika: uređaji, sesije, epizode, svi događaji |
| Sesija | `domovina-sesija` | jedna sesija događaj po događaj, ekrani na vremenskoj crti |
| Sadržaj | `domovina-sadrzaj` | epizode, kanali, osobe, ekrani: otvaranja, gledatelji, vrijeme |
| Rast i zadržavanje | `domovina-rast` | DAU/WAU/MAU, novi i povratni, tjedne kohorte, izvori novih |
| Lijevci i putanje | `domovina-lijevci` | lijevak sesije i korisnika, ulazni/izlazni ekrani, prijelazi |
| Sponzori | `domovina-sponzori` | prikazi, odslušano do kraja, klikovi po brendu i slotu |
| Zdravlje sustava | `domovina-zdravlje` | protok, kašnjenje, verzije, heartbeat, nepoznati događaji |

Klik na korisnika (bilo gdje) otvara **Korisnik**, klik na sesiju otvara
**Sesija** s vremenom postavljenim na tu sesiju, a klik na epizodu, kanal,
osobu ili rutu otvara stranicu na domovina.ai.

## Pojmovi

- **Korisnik** = `user_id` ako je prijavljen, inače `device_id`. U popisima
  korisnika, rastu i lijevku korisnika gost čiji se uređaj kasnije prijavio
  broji se kao taj korisnik; na profilu se njegovi gostujući događaji
  pridružuju. Tuđi prijavljeni događaji na istom uređaju ostaju tuđi.
- **Vrijeme na ekranu** je procjena: razmak do sljedećeg događaja u sesiji,
  najviše 300 s, pripisan zadnjem otvorenom ekranu. Zadnji događaj sesije
  dobiva 0. Točno vrijeme slušanja traži događaje playera (`play`, `pause`,
  `progress`, `complete`), kojih klijent još ne šalje.

## Izmjena

Dashboarde piše `grafana/dashboards.py`; JSON u `provisioning/` se ne
uređuje ručno (izmjena iz Grafana UI-ja ostaje do sljedećeg redeploya).

```bash
python3 grafana/dashboards.py                       # zapiše JSON
python3 grafana/dashboards.py --sql <user_id> <session_id> > /tmp/q.sql
# svaki upit s popunjenim makroima i FORMAT Null; izvrši ih kao reader
# na produkciji (clickhouse-client --multiquery) prije pusha
```

Pa commit, push i Coolify **Redeploy** (provisioning je ugrađen u image).

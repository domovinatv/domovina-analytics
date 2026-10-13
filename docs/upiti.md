# Gotovi upiti

Pokreću se u Grafani (Explore, datasource ClickHouse) kao `reader`.
`who` = `user_id` ako je prijavljen, inače `device_id`.

```sql
-- Tko je sada u aplikaciji
SELECT * FROM analytics.online_now WHERE app = 'domovina.ai' ORDER BY last_seen DESC;

-- Što je jedan korisnik radio (Supabase user id)
SELECT ts, event, route, video_id, platform, props
FROM analytics.events
WHERE user_id = '<uuid>' ORDER BY ts DESC LIMIT 500;

-- Svi uređaji jednog korisnika (spaja goste prije prijave)
SELECT DISTINCT device_id FROM analytics.events WHERE user_id = '<uuid>';

-- Dnevno aktivni, zadnjih 30 dana
SELECT * FROM analytics.daily_active
WHERE app = 'domovina.ai' AND day >= today() - 30 ORDER BY day, platform;

-- Prosječno trajanje sesije po platformi (donja granica: zadnji heartbeat)
SELECT platform, count() AS sesija, round(avg(duration_s) / 60, 1) AS min_prosjek,
       quantile(0.5)(duration_s) AS medijan_s
FROM analytics.sessions
WHERE app = 'domovina.ai' AND started >= now() - INTERVAL 7 DAY
GROUP BY platform;

-- Zadržavanje: od uređaja kojima je d0 prvi dan, koliko ih se vratilo
-- točno 1, 7 i 30 dana kasnije
WITH days AS (
  SELECT device_id,
         min(toDate(ts, 'Europe/Zagreb'))           AS d0,
         groupUniqArray(toDate(ts, 'Europe/Zagreb')) AS ds
  FROM analytics.events WHERE app = 'domovina.ai' GROUP BY device_id
)
SELECT d0, count() AS novih,
       countIf(has(ds, d0 + 1)) AS d1, countIf(has(ds, d0 + 7)) AS d7, countIf(has(ds, d0 + 30)) AS d30
FROM days WHERE d0 >= today() - 60 GROUP BY d0 ORDER BY d0;

-- Plaćeni sponzorski trenuci: prikazi i odslušano do kraja
SELECT JSONExtractString(props, 'slot_key') AS slot,
       countIf(event = 'sponsored_impression')   AS impressions,
       countIf(event = 'sponsored_play_through') AS play_through,
       countIf(event = 'sponsored_click')        AS clicks
FROM analytics.events
WHERE event LIKE 'sponsored_%' GROUP BY slot ORDER BY impressions DESC;
```

-- Pogledi za dashboarde i ručne upite. Obični (ne materijalizirani) pogledi:
-- ClickHouse ih nad mjesecima podataka vrti u milisekundama, a nema
-- dvostrukog stanja koje se može razići. Materijalizirani agregati tek
-- kad neki upit izmjereno postane spor.

-- Tko je u aplikaciji SADA: klijent flusha (i šalje heartbeat) svakih 30 s
-- dok je u prednjem planu, pa je 90 s tri propuštena flusha.
CREATE OR REPLACE VIEW analytics.online_now AS
SELECT
    app,
    if(user_id != '', user_id, device_id) AS who,
    user_id,
    device_id,
    any(platform)           AS platform,
    argMax(route, ts)       AS route,
    argMax(video_id, ts)    AS video_id,
    any(country)            AS country,
    any(city)               AS city,
    max(ts)                 AS last_seen
FROM analytics.events
WHERE ts > now64(3) - INTERVAL 90 SECOND
GROUP BY app, who, user_id, device_id;

-- Dnevno aktivni po aplikaciji i platformi.
CREATE OR REPLACE VIEW analytics.daily_active AS
SELECT
    app,
    toDate(ts, 'Europe/Zagreb') AS day,
    platform,
    uniqExact(if(user_id != '', user_id, device_id)) AS users,
    uniqExact(session_id)                            AS sessions,
    countIf(event = 'screen_view')                   AS screen_views
FROM analytics.events
GROUP BY app, day, platform;

-- Sesija = od prvog do zadnjeg događaja; trajanje je donja granica (zadnji
-- heartbeat), ne točno vrijeme zatvaranja.
CREATE OR REPLACE VIEW analytics.sessions AS
SELECT
    app,
    session_id,
    any(device_id)                       AS device_id,
    maxIf(user_id, user_id != '')        AS user_id,
    any(platform)                        AS platform,
    min(ts)                              AS started,
    max(ts)                              AS ended,
    dateDiff('second', min(ts), max(ts)) AS duration_s,
    countIf(event = 'screen_view')       AS screen_views,
    argMin(route, ts)                    AS entry_route,
    any(country)                         AS country
FROM analytics.events
GROUP BY app, session_id;

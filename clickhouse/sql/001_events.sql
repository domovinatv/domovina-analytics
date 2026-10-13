-- Jedna široka tablica za SVE događaje svih aplikacija (stupac `app`).
-- Novi događaj ne traži migraciju: ime ide u `event`, specifično u `props`
-- (JSON tekst, čita se s JSONExtract*). Stupac se dodaje tek kad se po
-- nekom polju filtrira u većini upita.
--
-- Idempotentno (IF NOT EXISTS) — `scripts/ch-apply.sh` ga smije vrtjeti
-- koliko god puta.

CREATE DATABASE IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.events
(
    event_id     UUID,
    -- Vrijeme na klijentu (sat izvan ±7 dana zamijeni vrijeme prijema).
    ts           DateTime64(3, 'UTC'),
    received_at  DateTime64(3, 'UTC'),
    event        LowCardinality(String),
    app          LowCardinality(String),
    platform     LowCardinality(String),
    app_version  LowCardinality(String),
    -- Supabase auth.users.id; prazno za gosta.
    user_id      String,
    -- Trajni ID instalacije / preglednika (localStorage, SharedPreferences).
    device_id    String,
    session_id   String,
    route        String,
    video_id     String,
    channel      String,
    locale       LowCardinality(String),
    screen_w     UInt16,
    screen_h     UInt16,
    country      LowCardinality(String),
    region       String,
    city         String,
    browser      LowCardinality(String),
    os           LowCardinality(String),
    props        String CODEC(ZSTD(3)),

    INDEX idx_user   user_id   TYPE bloom_filter GRANULARITY 4,
    INDEX idx_device device_id TYPE bloom_filter GRANULARITY 4,
    INDEX idx_video  video_id  TYPE bloom_filter GRANULARITY 4
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (app, event, ts)
SETTINGS index_granularity = 8192;

-- Rok čuvanja: 25 mjeseci, kako piše u politici privatnosti aplikacije
-- (domovina.ai, odjeljak „Analitika korištenja”). Mijenjaš li rok, mijenjaj
-- i taj tekst (legalPrivacyAnalyticsBody u oba ARB-a).
--
-- Particije su mjesečne, pa ttl_only_drop_parts briše cijele dijelove
-- umjesto prepisivanja redaka. materialize_ttl_after_modify = 0: ponovno
-- vrćenje ch-apply.sh ne pokreće mutaciju nad cijelom tablicom; TTL se
-- primjenjuje pri spajanju dijelova.

ALTER TABLE analytics.events
    MODIFY TTL toDateTime(ts) + INTERVAL 25 MONTH
    SETTINGS materialize_ttl_after_modify = 0;

ALTER TABLE analytics.events MODIFY SETTING ttl_only_drop_parts = 1;

# Shema, korisnici i memorijski limit ugrađeni u image. Coolify za Docker
# Compose resurs ne kopira datoteke repoa na host, pa bind mount iz repoa
# na serveru postane prazna mapa (izmjereno 14. 10. 2026.).
FROM clickhouse/clickhouse-server:25.8
COPY --chmod=755 apply.sh /docker-entrypoint-initdb.d/apply.sh
COPY sql/ /analytics/sql/
COPY config.d/memory.xml /etc/clickhouse-server/config.d/memory.xml

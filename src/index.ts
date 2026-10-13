// domovina-analytics ingest Worker.
//
//   klijent ──POST {INGEST_PATH}──► fetch()  ──► 204 odmah
//                                     └─ waitUntil: insert u ClickHouse
//                                          └─ ne uspije? → Queue
//   Queue ──► queue() ──► ponovni insert (retry s odgodom, pa DLQ)
//
// Queue je REZERVA, ne glavni put: dok ClickHouse radi, Queue ne vidi ništa
// i ne košta ništa. Cijene i izračun: docs/troskovi.md.

import { ClickHouseError, insertRows, type ClickHouseEnv } from './clickhouse';
import { isBot, serverFields, type StoredRow } from './enrich';
import { chTime, MAX_BODY_BYTES, parseEnvelope } from './validate';

export interface Env extends ClickHouseEnv {
  INGEST_PATH: string;
  /// Zarezom odvojeni popis dopuštenih `Origin` vrijednosti; `*` na kraju
  /// stavke je prefiks (npr. `http://localhost:*`).
  ALLOWED_ORIGINS: string;
  BUFFER: Queue<QueuedBatch>;
  LIMITER?: RateLimit;
}

export interface QueuedBatch {
  rows: StoredRow[];
}

function originAllowed(origin: string, list: string): boolean {
  return list
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .some((rule) => (rule.endsWith('*') ? origin.startsWith(rule.slice(0, -1)) : origin === rule));
}

function corsHeaders(origin: string | null): Record<string, string> {
  if (!origin) return {};
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
    Vary: 'Origin',
  };
}

function reply(status: number, origin: string | null, body?: string): Response {
  return new Response(body ?? null, {
    status,
    headers: { 'Cache-Control': 'no-store', ...corsHeaders(origin) },
  });
}

export async function writeOrBuffer(env: Env, rows: StoredRow[]): Promise<'inserted' | 'buffered' | 'dropped'> {
  try {
    await insertRows(env, rows);
    return 'inserted';
  } catch (err) {
    // 400 = ClickHouse nije mogao parsirati podatak. Ponovni pokušaj to
    // neće popraviti; validacija u validate.ts je propustila nešto i to se
    // mora vidjeti u logu, ne vrtjeti u Queueu do DLQ-a.
    if (err instanceof ClickHouseError && err.status === 400) {
      console.error('ingest: ClickHouse odbio podatke', err.message, JSON.stringify(rows[0]));
      return 'dropped';
    }
    console.warn('ingest: ClickHouse nedostupan, ide u Queue', String(err));
    await env.BUFFER.send({ rows });
    return 'buffered';
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin');

    if (url.pathname !== env.INGEST_PATH) return reply(404, null);
    if (origin && !originAllowed(origin, env.ALLOWED_ORIGINS)) return reply(403, null);
    if (request.method === 'OPTIONS') return reply(204, origin);
    if (request.method !== 'POST') return reply(405, origin);

    const declared = Number(request.headers.get('Content-Length') ?? '0');
    if (declared > MAX_BODY_BYTES) return reply(413, origin);

    const ua = request.headers.get('User-Agent') ?? '';
    // Bot dobiva 204 kao i svi — bez signala da je prepoznat.
    if (isBot(ua)) return reply(204, origin);

    const raw = await request.text();
    const now = Date.now();
    const parsed = parseEnvelope(raw, now);
    if (!parsed.ok) return reply(parsed.status, origin, parsed.reason);
    if (parsed.rows.length === 0) return reply(204, origin);

    if (env.LIMITER) {
      const key = parsed.deviceId || request.headers.get('CF-Connecting-IP') || 'unknown';
      const { success } = await env.LIMITER.limit({ key });
      if (!success) return reply(429, origin);
    }

    const extra = serverFields(ua, request.cf as Record<string, string> | undefined, chTime(now));
    const rows: StoredRow[] = parsed.rows.map((r) => ({ ...r, ...extra }));
    ctx.waitUntil(writeOrBuffer(env, rows).catch((e) => console.error('ingest: izgubljen batch', String(e))));
    return reply(204, origin);
  },

  async queue(batch: MessageBatch<QueuedBatch>, env: Env): Promise<void> {
    const rows = batch.messages.flatMap((m) => m.body.rows);
    try {
      await insertRows(env, rows, 15_000);
      batch.ackAll();
      return;
    } catch (err) {
      if (!(err instanceof ClickHouseError && err.status === 400)) {
        console.warn('buffer: ClickHouse i dalje nedostupan', String(err));
        batch.retryAll({ delaySeconds: 60 });
        return;
      }
    }
    // Jedna poruka s lošim podatkom ne smije zadržati ostale: pokušaj
    // pojedinačno, loša ide kroz retry u DLQ, ispravne se potvrde.
    for (const m of batch.messages) {
      try {
        await insertRows(env, m.body.rows, 15_000);
        m.ack();
      } catch (err) {
        console.error('buffer: poruka odbijena', String(err));
        m.retry({ delaySeconds: 300 });
      }
    }
  },
} satisfies ExportedHandler<Env, QueuedBatch>;

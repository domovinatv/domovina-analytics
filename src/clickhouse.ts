// Insert u ClickHouse preko HTTP sučelja (`/?query=INSERT … FORMAT JSONEachRow`).
//
// `async_insert` skuplja male batcheve u serverski buffer pa tisuće malih
// zahtjeva ne rade tisuće dijelova (partova) na disku. `wait_for_async_insert=1`
// znači da 200 stiže tek kad je buffer zapisan — inače Worker ne bi znao je
// li podatak stvarno sjeo i kad treba pasti na Queue.

import type { StoredRow } from './enrich';

export interface ClickHouseEnv {
  CH_URL: string;
  CH_USER: string;
  CH_PASSWORD: string;
  /// Cloudflare Access service token ispred `ch-ingest` hostnamea; prazno =
  /// bez Accessa (lokalni razvoj).
  CF_ACCESS_CLIENT_ID?: string;
  CF_ACCESS_CLIENT_SECRET?: string;
}

const QUERY = 'INSERT INTO analytics.events FORMAT JSONEachRow';

export class ClickHouseError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function insertRows(env: ClickHouseEnv, rows: StoredRow[], timeoutMs = 5_000): Promise<void> {
  if (rows.length === 0) return;
  const url = new URL(env.CH_URL);
  url.searchParams.set('query', QUERY);
  url.searchParams.set('async_insert', '1');
  url.searchParams.set('wait_for_async_insert', '1');

  const headers: Record<string, string> = {
    'Content-Type': 'application/x-ndjson',
    'X-ClickHouse-User': env.CH_USER,
    'X-ClickHouse-Key': env.CH_PASSWORD,
  };
  if (env.CF_ACCESS_CLIENT_ID && env.CF_ACCESS_CLIENT_SECRET) {
    headers['CF-Access-Client-Id'] = env.CF_ACCESS_CLIENT_ID;
    headers['CF-Access-Client-Secret'] = env.CF_ACCESS_CLIENT_SECRET;
  }

  const res = await fetch(url, {
    method: 'POST',
    headers,
    body: rows.map((r) => JSON.stringify(r)).join('\n'),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) {
    const body = (await res.text()).slice(0, 500);
    throw new ClickHouseError(`ClickHouse ${res.status}: ${body}`, res.status);
  }
}

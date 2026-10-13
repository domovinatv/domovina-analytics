// Ulazni ugovor: ono što klijent šalje (`docs/ugovor.md`) → redak za ClickHouse.
//
// Jedan neispravan redak obara CIJELI insert (ClickHouse ne preskače redak
// koji ne parsira u UUID ili broj), a odbijeni batch bi u Queueu išao u
// ponovne pokušaje do DLQ-a. Zato se sve što ide u tipizirani stupac ovdje
// ili popravi ili odbaci — nikad se ne prosljeđuje „pa će baza reći”.

export const MAX_BODY_BYTES = 64_000;
export const MAX_EVENTS = 50;
export const MAX_PROPS_BYTES = 4_096;
/// Sat klijenta zna biti krivo namješten; izvan ovog prozora vrijeme
/// događaja postaje vrijeme prijema.
export const MAX_CLOCK_SKEW_MS = 7 * 24 * 3600 * 1000;

const EVENT_NAME = /^[a-z][a-z0-9_]{1,63}$/;
const TOKEN = /^[A-Za-z0-9_.:-]{1,64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PLATFORMS = new Set(['web', 'ios', 'android', 'tv', 'macos', 'windows', 'linux']);

export interface ClientEvent {
  id?: unknown;
  t?: unknown;
  n?: unknown;
  route?: unknown;
  video_id?: unknown;
  channel?: unknown;
  props?: unknown;
}

export interface Envelope {
  v?: unknown;
  app?: unknown;
  device_id?: unknown;
  session_id?: unknown;
  user_id?: unknown;
  platform?: unknown;
  app_version?: unknown;
  locale?: unknown;
  screen?: unknown;
  events?: unknown;
}

/// Stupci tablice `analytics.events` osim onih koje dodaje server
/// (`enrich.ts`). Imena = imena stupaca, jer se šalju kao JSONEachRow.
export interface EventRow {
  event_id: string;
  ts: string;
  event: string;
  app: string;
  platform: string;
  app_version: string;
  user_id: string;
  device_id: string;
  session_id: string;
  route: string;
  video_id: string;
  channel: string;
  locale: string;
  screen_w: number;
  screen_h: number;
  props: string;
}

export type ParseResult =
  | { ok: true; rows: EventRow[]; deviceId: string; dropped: number }
  | { ok: false; status: number; reason: string };

export function token(v: unknown): string {
  return typeof v === 'string' && TOKEN.test(v) ? v : '';
}

export function text(v: unknown, max: number): string {
  if (typeof v !== 'string') return '';
  // Kontrolni znakovi nemaju što tražiti u ruti ili ID-u.
  const clean = v.replace(/[\u0000-\u001f\u007f]/g, '');
  return clean.length > max ? clean.slice(0, max) : clean;
}

function dim(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v)
    ? Math.min(65_535, Math.max(0, Math.round(v)))
    : 0;
}

/// `YYYY-MM-DD hh:mm:ss.sss` u UTC — format koji DateTime64(3) čita bez
/// `best_effort` parsera.
export function chTime(ms: number): string {
  return new Date(ms).toISOString().replace('T', ' ').replace('Z', '');
}

export function parseEnvelope(raw: string, nowMs: number): ParseResult {
  if (raw.length > MAX_BODY_BYTES) {
    return { ok: false, status: 413, reason: 'too_large' };
  }
  let env: Envelope;
  try {
    env = JSON.parse(raw) as Envelope;
  } catch {
    return { ok: false, status: 400, reason: 'bad_json' };
  }
  if (env === null || typeof env !== 'object' || !Array.isArray(env.events)) {
    return { ok: false, status: 400, reason: 'bad_envelope' };
  }

  const app = token(env.app);
  const deviceId = token(env.device_id);
  const sessionId = token(env.session_id);
  if (!app || !sessionId) {
    return { ok: false, status: 400, reason: 'missing_ids' };
  }
  const platform =
    typeof env.platform === 'string' && PLATFORMS.has(env.platform) ? env.platform : 'unknown';
  const screen = Array.isArray(env.screen) ? env.screen : [];

  const common = {
    app,
    platform,
    app_version: text(env.app_version, 32),
    user_id: typeof env.user_id === 'string' && UUID.test(env.user_id) ? env.user_id.toLowerCase() : '',
    device_id: deviceId,
    session_id: sessionId,
    locale: text(env.locale, 16),
    screen_w: dim(screen[0]),
    screen_h: dim(screen[1]),
  };

  const rows: EventRow[] = [];
  let dropped = 0;
  const events = (env.events as unknown[]).slice(0, MAX_EVENTS);
  dropped += (env.events as unknown[]).length - events.length;

  for (const item of events) {
    if (item === null || typeof item !== 'object') {
      dropped++;
      continue;
    }
    const e = item as ClientEvent;
    if (typeof e.n !== 'string' || !EVENT_NAME.test(e.n)) {
      dropped++;
      continue;
    }
    let props = '{}';
    if (e.props !== undefined && e.props !== null) {
      if (typeof e.props !== 'object' || Array.isArray(e.props)) {
        dropped++;
        continue;
      }
      props = JSON.stringify(e.props);
      if (props.length > MAX_PROPS_BYTES) {
        dropped++;
        continue;
      }
    }
    const t =
      typeof e.t === 'number' && Number.isFinite(e.t) && Math.abs(e.t - nowMs) <= MAX_CLOCK_SKEW_MS
        ? e.t
        : nowMs;
    rows.push({
      ...common,
      event_id: typeof e.id === 'string' && UUID.test(e.id) ? e.id.toLowerCase() : crypto.randomUUID(),
      ts: chTime(t),
      event: e.n,
      route: text(e.route, 512),
      video_id: token(e.video_id),
      channel: text(e.channel, 128),
      props,
    });
  }

  return { ok: true, rows, deviceId, dropped };
}

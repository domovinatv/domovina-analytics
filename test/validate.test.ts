import { describe, expect, it } from 'vitest';
import { browserOf, isBot, osOf } from '../src/enrich';
import { MAX_EVENTS, parseEnvelope } from '../src/validate';

const NOW = Date.parse('2026-10-14T12:00:00.000Z');
const UID = '3f2b8c1e-9a4d-4e2f-8b1a-0c9d8e7f6a5b';

function env(events: unknown[], extra: Record<string, unknown> = {}) {
  return JSON.stringify({
    v: 1,
    app: 'domovina.ai',
    device_id: 'dev_abc123',
    session_id: 'ses_xyz',
    platform: 'web',
    app_version: '2.0.186',
    locale: 'hr',
    screen: [390, 844],
    events,
    ...extra,
  });
}

describe('parseEnvelope', () => {
  it('pretvara ispravan događaj u redak sa zajedničkim poljima', () => {
    const r = parseEnvelope(
      env([{ id: UID, t: NOW - 1000, n: 'screen_view', route: '/v/abc', video_id: 'abc', props: { a: 1 } }], {
        user_id: UID.toUpperCase(),
      }),
      NOW,
    );
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.rows).toHaveLength(1);
    expect(r.rows[0]).toMatchObject({
      event_id: UID,
      ts: '2026-10-14 11:59:59.000',
      event: 'screen_view',
      app: 'domovina.ai',
      platform: 'web',
      user_id: UID,
      device_id: 'dev_abc123',
      route: '/v/abc',
      video_id: 'abc',
      screen_w: 390,
      screen_h: 844,
      props: '{"a":1}',
    });
  });

  it('odbacuje događaje s lošim imenom ili prevelikim props, ostale zadržava', () => {
    const r = parseEnvelope(
      env([{ n: 'Bad Name' }, { n: 'ok_event', props: { x: 'y'.repeat(5000) } }, { n: 'ok_event' }, 'x']),
      NOW,
    );
    expect(r.ok && r.rows.length).toBe(1);
    expect(r.ok && r.dropped).toBe(3);
  });

  it('nikad ne propušta nevaljan UUID u tipizirani stupac', () => {
    const r = parseEnvelope(env([{ id: 'not-a-uuid', n: 'x_y' }], { user_id: 'drop table' }), NOW);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.rows[0].event_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(r.rows[0].user_id).toBe('');
  });

  it('sat izvan prozora od 7 dana postaje vrijeme prijema', () => {
    const r = parseEnvelope(env([{ n: 'x_y', t: NOW - 30 * 864e5 }]), NOW);
    expect(r.ok && r.rows[0].ts).toBe('2026-10-14 12:00:00.000');
  });

  it(`reže batch na ${MAX_EVENTS} događaja`, () => {
    const r = parseEnvelope(env(Array.from({ length: 80 }, () => ({ n: 'heartbeat' }))), NOW);
    expect(r.ok && r.rows.length).toBe(MAX_EVENTS);
    expect(r.ok && r.dropped).toBe(30);
  });

  it('traži app i session_id; device_id smije izostati', () => {
    expect(parseEnvelope(env([], { session_id: '' }), NOW)).toMatchObject({ ok: false, status: 400 });
    expect(parseEnvelope(env([{ n: 'x_y' }], { device_id: undefined }), NOW).ok).toBe(true);
  });

  it('odbija loš JSON i prevelik body', () => {
    expect(parseEnvelope('{', NOW)).toMatchObject({ ok: false, status: 400 });
    expect(parseEnvelope('x'.repeat(70_000), NOW)).toMatchObject({ ok: false, status: 413 });
  });

  it('nepoznata platforma postaje unknown, kontrolni znakovi iz rute nestaju', () => {
    const r = parseEnvelope(env([{ n: 'x_y', route: '/a\n/b' }], { platform: 'amiga' }), NOW);
    expect(r.ok && r.rows[0].platform).toBe('unknown');
    expect(r.ok && r.rows[0].route).toBe('/a/b');
  });
});

describe('User-Agent', () => {
  const brave =
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
  const iosSafari =
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1';
  const edge = brave + ' Edg/141.0.0.0';

  it('prepoznaje preglednik i OS', () => {
    expect([browserOf(brave), osOf(brave)]).toEqual(['chrome', 'macos']);
    expect([browserOf(iosSafari), osOf(iosSafari)]).toEqual(['safari', 'ios']);
    expect(browserOf(edge)).toBe('edge');
    expect(browserOf('Dart/3.9 (dart:io)')).toBe('app');
  });

  it('native aplikacija nije bot, crawleri i prazan UA jesu', () => {
    expect(isBot('Dart/3.9 (dart:io)')).toBe(false);
    expect(isBot(brave)).toBe(false);
    expect(isBot('')).toBe(true);
    expect(isBot('Mozilla/5.0 (compatible; Googlebot/2.1)')).toBe(true);
    expect(isBot('WhatsApp/2.23')).toBe(true);
  });
});

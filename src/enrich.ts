// Ono što server zna bolje od klijenta: vrijeme prijema, geografija iz
// Cloudflareovog `request.cf` i grubi preglednik/OS iz User-Agenta.
//
// IP adresa se NE sprema — koristi se samo kao ključ rate limitera.

import type { EventRow } from './validate';

export interface ServerFields {
  received_at: string;
  country: string;
  region: string;
  city: string;
  browser: string;
  os: string;
}

export type StoredRow = EventRow & ServerFields;

const BOT = /bot|crawl|spider|slurp|headless|lighthouse|pagespeed|preview|facebookexternalhit|whatsapp|telegram|curl|wget|python|go-http|okhttp\/[0-2]\./i;

export function isBot(ua: string): boolean {
  // Native aplikacije šalju vlastiti UA (`dart:io`/`Dart/3.x`) — to nije bot.
  if (/^Dart\//.test(ua)) return false;
  return ua === '' || BOT.test(ua);
}

/// Redoslijed je bitan: Edge i Opera nose i „Chrome”, Chrome nosi „Safari”.
/// Brave se u UA-u ne razlikuje od Chromea (namjerno) pa je ovdje Chrome.
export function browserOf(ua: string): string {
  if (/^Dart\//.test(ua)) return 'app';
  if (/Edg(e|A|iOS)?\//.test(ua)) return 'edge';
  if (/OPR\/|Opera/.test(ua)) return 'opera';
  if (/SamsungBrowser\//.test(ua)) return 'samsung';
  if (/Firefox\/|FxiOS\//.test(ua)) return 'firefox';
  if (/CriOS\//.test(ua)) return 'chrome';
  if (/Chrome\//.test(ua)) return 'chrome';
  if (/Safari\//.test(ua)) return 'safari';
  return 'other';
}

export function osOf(ua: string): string {
  if (/iPhone|iPad|iPod/.test(ua)) return 'ios';
  if (/Android/.test(ua)) return 'android';
  if (/Windows/.test(ua)) return 'windows';
  if (/Mac OS X|Macintosh/.test(ua)) return 'macos';
  if (/CrOS/.test(ua)) return 'chromeos';
  if (/Linux/.test(ua)) return 'linux';
  return 'other';
}

interface CfGeo {
  country?: string;
  region?: string;
  city?: string;
}

export function serverFields(ua: string, cf: CfGeo | undefined, receivedAt: string): ServerFields {
  return {
    received_at: receivedAt,
    country: typeof cf?.country === 'string' ? cf.country : '',
    region: typeof cf?.region === 'string' ? cf.region : '',
    city: typeof cf?.city === 'string' ? cf.city : '',
    browser: browserOf(ua),
    os: osOf(ua),
  };
}

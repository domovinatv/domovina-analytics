#!/usr/bin/env python3
"""Generira Grafana dashboarde u grafana/provisioning/dashboards/*.json.

Dashboardi dijele isti datasource, iste izraze (tko je korisnik, vrijeme na
ekranu, linkovi) i isti izgled, pa se ne pišu ručno nego odavde. Ručna
izmjena JSON-a se pregazi pri sljedećem pokretanju.

    python3 grafana/dashboards.py            # zapiši JSON
    python3 grafana/dashboards.py --sql      # ispiši upite s popunjenim
                                             # makroima (za provjeru u CH)
"""
import json
import pathlib
import re
import sys

OUT = pathlib.Path(__file__).parent / "provisioning" / "dashboards"
DS = {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"}
APP = "app = 'domovina.ai'"
TAG = "domovina"
SITE = "https://domovina.ai"

# Gost je device_id; nakon prijave isti uređaj pripada korisniku.
WHO = "if(user_id != '', user_id, device_id)"

# Korisnik sa svim događajima: prijavljeni pod svojim user_id, plus gostujući
# (prije prijave) s uređaja na kojima se kasnije prijavio. Tuđi prijavljeni
# događaji na istom uređaju ostaju tuđi.
USER = (
    f"{APP} AND (user_id = ${{who:sqlstring}} OR (user_id = '' AND ("
    "device_id = ${who:sqlstring} OR device_id IN ("
    "SELECT device_id FROM analytics.events WHERE user_id = ${who:sqlstring}))))"
)

# Spojeni identitet za popise korisnika: gost čiji se uređaj kasnije prijavio
# broji se kao taj korisnik, ne kao zaseban posjetitelj.
STITCHED = (
    "(SELECT e.*, if(e.user_id != '', e.user_id, if(d.u != '', d.u, e.device_id)) AS who"
    " FROM analytics.events AS e"
    " LEFT JOIN (SELECT device_id, any(user_id) AS u FROM analytics.events"
    f" WHERE {APP} AND user_id != '' GROUP BY device_id) AS d USING device_id"
    " WHERE e.{where})"
)


def stitched(where):
    return STITCHED.replace("{where}", where)


# Vrijeme na ekranu: razmak do sljedećeg događaja u sesiji, najviše 300 s,
# pripisan ekranu na kojem je korisnik tada bio (app_background i
# session_start nemaju rutu, pa se uzima zadnja poznata). Procjena, ne
# mjerenje: zadnji događaj sesije dobiva 0, a heartbeat svakih 30 s je
# gornja granica greške dok radi.
def screen_time(where):
    return (
        "(SELECT *,"
        " least(dateDiff('second', ts, leadInFrame(ts, 1, ts) OVER w), 300) AS dwell_s,"
        " ifNull(anyLast(nullIf(route, '')) OVER w_cur, '') AS screen,"
        " extract(screen, '^/(?:v|m|yt)/([^/?#]+)') AS vid,"
        " extract(screen, '^/c/([^/?#]+)') AS ch,"
        " extract(screen, '^/p/([^/?#]+)') AS person"
        f" FROM analytics.events WHERE {where}"
        " WINDOW w AS (PARTITION BY session_id ORDER BY ts ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING),"
        " w_cur AS (PARTITION BY session_id ORDER BY ts ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW))"
    )


# Ruta bez ID-a, za putanje i grupiranje ekrana.
SCREEN_KIND = "replaceRegexpOne(route, '^/(v|m|yt|c|p)/.*', '/\\\\1/…')"

# --- linkovi -----------------------------------------------------------------

L_USER = {"title": "Profil korisnika", "url": "/d/domovina-korisnik/korisnik?var-who=${__value.raw}&from=now-90d&to=now"}
L_SESSION = {
    "title": "Tijek sesije",
    "url": "/d/domovina-sesija/sesija?var-session=${__value.raw}"
    "&from=${__data.fields.od_ms}&to=${__data.fields.do_ms}",
}
L_VIDEO = {"title": "Otvori epizodu", "url": SITE + "/v/${__value.raw}", "targetBlank": True}
L_CHANNEL = {"title": "Otvori kanal", "url": SITE + "/c/${__value.raw}", "targetBlank": True}
L_PERSON = {"title": "Otvori osobu", "url": SITE + "/p/${__value.raw}", "targetBlank": True}
L_ROUTE = {"title": "Otvori", "url": SITE + "${__value.raw}", "targetBlank": True}

# Stupac → link; vrijedi u svakoj tablici koja ima stupac tog imena.
COLUMN_LINKS = {
    "korisnik": L_USER,
    "who": L_USER,
    "sesija": L_SESSION,
    "video_id": L_VIDEO,
    "epizoda": L_VIDEO,
    "kanal": L_CHANNEL,
    "osoba": L_PERSON,
    "ruta": L_ROUTE,
}
COLUMN_UNITS = {
    "vrijeme": "dtdurations",
    "vrijeme_ukupno": "dtdurations",
    "vrijeme_po_korisniku": "dtdurations",
    "na_ekranu": "dtdurations",
    "trajanje": "dtdurations",
    "kasnjenje_p50": "ms",
    "kasnjenje_p95": "ms",
}
HIDDEN = ["od_ms", "do_ms"]


# --- paneli ------------------------------------------------------------------

def target(sql, fmt=1):
    # format: 0 = time series, 1 = table
    return {
        "refId": "A",
        "datasource": DS,
        "editorType": "sql",
        "format": fmt,
        "queryType": "timeseries" if fmt == 0 else "table",
        "rawSql": sql,
    }


def panel(kind, title, sql, w, h, desc=None, fmt=1, options=None, defaults=None, overrides=None):
    p = {
        "type": kind,
        "title": title,
        "datasource": DS,
        "gridPos": {"w": w, "h": h},
        "targets": [target(sql, fmt)],
        "fieldConfig": {"defaults": defaults or {}, "overrides": overrides or []},
        "options": options or {},
    }
    if desc:
        p["description"] = desc
    return p


def stat(title, sql, w=4, h=4, unit=None, desc=None, text=False):
    d = {"color": {"mode": "fixed", "fixedColor": "text"}}
    if unit:
        d["unit"] = unit
    return panel(
        "stat", title, sql, w, h, desc,
        options={
            "reduceOptions": {"values": False, "calcs": ["lastNotNull"], "fields": "/.*/" if text else ""},
            "textMode": "value_and_name" if text else "value",
            "colorMode": "none",
            "graphMode": "none",
            "justifyMode": "center",
            "wideLayout": True,
        },
        defaults=d,
    )


def table(title, sql, w=12, h=10, desc=None, heat=None, sort=None, filterable=True):
    overrides = []
    for col, link in COLUMN_LINKS.items():
        overrides.append({"matcher": {"id": "byName", "options": col}, "properties": [{"id": "links", "value": [link]}]})
    for col, unit in COLUMN_UNITS.items():
        overrides.append({"matcher": {"id": "byName", "options": col}, "properties": [{"id": "unit", "value": unit}]})
    for col in HIDDEN:
        overrides.append({"matcher": {"id": "byName", "options": col}, "properties": [{"id": "custom.hidden", "value": True}]})
    if heat:
        # Stupci kao toplinska karta (regex po imenu), npr. sati ili tjedni.
        overrides.append({
            "matcher": {"id": "byRegexp", "options": heat["cols"]},
            "properties": [
                {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}},
                {"id": "color", "value": {"mode": "continuous-BlPu"}},
                {"id": "min", "value": 0},
                {"id": "custom.width", "value": heat.get("width", 46)},
                {"id": "custom.align", "value": "center"},
            ] + ([{"id": "unit", "value": heat["unit"]}] if heat.get("unit") else [])
            + ([{"id": "max", "value": heat["max"]}] if "max" in heat else []),
        })
    options = {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}}
    if sort:
        options["sortBy"] = [{"displayName": sort, "desc": True}]
    return panel(
        "table", title, sql, w, h, desc,
        options=options,
        defaults={"custom": {"filterable": filterable, "align": "auto", "inspect": True}},
        overrides=overrides,
    )


def timeseries(title, sql, w=12, h=8, desc=None, bars=False, stack=False, unit=None):
    custom = {
        "drawStyle": "bars" if bars else "line",
        "lineWidth": 2,
        "fillOpacity": 70 if bars else 12,
        "gradientMode": "opacity",
        "showPoints": "never",
        "barAlignment": 0,
        "stacking": {"mode": "normal" if stack else "none"},
        "axisSoftMin": 0,
    }
    d = {"custom": custom, "color": {"mode": "palette-classic"}}
    if unit:
        d["unit"] = unit
    return panel(
        "timeseries", title, sql, w, h, desc, fmt=0,
        options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi", "sort": "desc"}},
        defaults=d,
    )


def barchart(title, sql, x, w=12, h=8, desc=None, horizontal=False, unit=None):
    d = {"color": {"mode": "palette-classic"}, "custom": {"fillOpacity": 80, "gradientMode": "hue", "lineWidth": 0}}
    if unit:
        d["unit"] = unit
    return panel(
        "barchart", title, sql, w, h, desc,
        options={
            "xField": x,
            "orientation": "horizontal" if horizontal else "vertical",
            "showValue": "auto",
            "legend": {"showLegend": False},
            "barWidth": 0.8,
            "xTickLabelRotation": 0,
            "tooltip": {"mode": "single"},
        },
        defaults=d,
    )


def funnel(title, sql, w=12, h=8, desc=None):
    return panel(
        "bargauge", title, sql, w, h, desc,
        options={
            "orientation": "horizontal",
            "displayMode": "gradient",
            "valueMode": "color",
            "showUnfilled": True,
            "namePlacement": "top",
            "reduceOptions": {"values": False, "calcs": ["lastNotNull"], "fields": ""},
            "minVizHeight": 16,
            "maxVizHeight": 36,
        },
        defaults={"min": 0, "color": {"mode": "continuous-BlPu"}},
    )


def state_timeline(title, sql, w=24, h=6, desc=None):
    return panel(
        "state-timeline", title, sql, w, h, desc, fmt=1,
        options={
            "showValue": "auto",
            "mergeValues": True,
            "alignValue": "left",
            "rowHeight": 0.85,
            "legend": {"showLegend": False},
            "tooltip": {"mode": "single"},
        },
        defaults={"color": {"mode": "palette-classic-by-name"}, "custom": {"fillOpacity": 80, "lineWidth": 0}},
    )


def text(content, w=24, h=3):
    return {"type": "text", "title": "", "gridPos": {"w": w, "h": h}, "options": {"mode": "markdown", "content": content}}


def row(title):
    return {"type": "row", "title": title, "collapsed": False, "gridPos": {"w": 24, "h": 1}, "panels": []}


# --- dashboard ---------------------------------------------------------------

def layout(panels):
    """Slaže panele s lijeva na desno pa u novi red, kao tekst."""
    x = y = row_h = 0
    for i, p in enumerate(panels, start=1):
        p["id"] = i
        g = p["gridPos"]
        if p["type"] == "row" or x + g["w"] > 24:
            x, y, row_h = 0, y + row_h, 0
        g["x"], g["y"] = x, y
        x += g["w"]
        row_h = max(row_h, g["h"])
        if p["type"] == "row":
            x, y, row_h = 0, y + 1, 0
    return panels


def query_var(name, label, sql, refresh=2):
    return {
        "name": name,
        "label": label,
        "type": "query",
        "datasource": DS,
        "query": sql,
        "definition": sql,
        "refresh": refresh,
        "includeAll": False,
        "multi": False,
        "allowCustomValue": True,
        "options": [],
        "current": {},
        "sort": 0,
    }


def dashboard(uid, title, panels, time="now-7d", refresh="1m", variables=None, desc=""):
    return {
        "uid": uid,
        "title": title,
        "description": desc,
        "tags": [TAG],
        "timezone": "Europe/Zagreb",
        "refresh": refresh,
        "time": {"from": time, "to": "now"},
        "schemaVersion": 39,
        "graphTooltip": 1,
        "editable": True,
        "links": [{
            "title": "Analitika",
            "type": "dashboards",
            "tags": [TAG],
            "asDropdown": False,
            "includeVars": False,
            "keepTime": False,
            "icon": "external link",
        }],
        "templating": {"list": variables or []},
        "panels": layout(panels),
    }


# --- 1. Pregled ---------------------------------------------------------------

def pregled():
    return dashboard("domovina-pregled", "DOMOVINA.ai — pregled", [
        stat("Online sada", f"SELECT count() AS online FROM analytics.online_now WHERE {APP}"),
        stat("Danas: korisnika", f"SELECT uniqExact({WHO}) FROM analytics.events WHERE {APP} AND toDate(ts, 'Europe/Zagreb') = today()"),
        stat("Danas: sesija", f"SELECT uniqExact(session_id) FROM analytics.events WHERE {APP} AND toDate(ts, 'Europe/Zagreb') = today()"),
        table("Tko je sada u aplikaciji",
              f"SELECT who AS korisnik, user_id != '' AS prijavljen, platform, route AS ruta, video_id, country, city, last_seen FROM analytics.online_now WHERE {APP} ORDER BY last_seen DESC",
              w=12, h=10, desc="Klik na korisnika otvara njegov profil."),
        timeseries("Aktivni korisnici",
                   f"SELECT $__timeInterval(ts) AS time, platform, uniqExact({WHO}) AS users FROM analytics.events WHERE {APP} AND $__timeFilter(ts) GROUP BY time, platform ORDER BY time",
                   w=12, h=6),
        table("Najgledanije epizode",
              f"SELECT video_id, count() AS prikazi, uniqExact({WHO}) AS korisnika FROM analytics.events WHERE {APP} AND event = 'screen_view' AND video_id != '' AND $__timeFilter(ts) GROUP BY video_id ORDER BY prikazi DESC LIMIT 50",
              w=12, h=10),
        table("Ekrani",
              f"SELECT route AS ruta, count() AS prikazi FROM analytics.events WHERE {APP} AND event = 'screen_view' AND $__timeFilter(ts) GROUP BY route ORDER BY prikazi DESC LIMIT 50",
              w=12, h=10),
        table("Platforme i preglednici",
              f"SELECT platform, browser, os, uniqExact(device_id) AS uredaja FROM analytics.events WHERE {APP} AND $__timeFilter(ts) GROUP BY platform, browser, os ORDER BY uredaja DESC",
              w=12, h=8),
        table("Države i gradovi",
              f"SELECT country, city, uniqExact(device_id) AS uredaja FROM analytics.events WHERE {APP} AND $__timeFilter(ts) GROUP BY country, city ORDER BY uredaja DESC LIMIT 50",
              w=12, h=8),
        table("Odakle dolaze (referrer, utm)",
              f"SELECT JSONExtractString(props, 'referrer') AS referrer, JSONExtractString(props, 'utm_source') AS utm_source, count() AS sesija FROM analytics.events WHERE {APP} AND event = 'session_start' AND $__timeFilter(ts) GROUP BY referrer, utm_source ORDER BY sesija DESC LIMIT 50",
              w=24, h=8),
    ], time="now-24h", refresh="10s", desc="Što se događa sada i danas.")


# --- 2. Korisnici (popis) -------------------------------------------------------

def korisnici():
    ev = stitched(f"{APP} AND $__timeFilter(e.ts)")
    allev = stitched(APP)
    first = f"(SELECT who, min(ts) AS first_ts FROM {allev} GROUP BY who)"
    return dashboard("domovina-korisnici", "Korisnici", [
        stat("Korisnika", f"SELECT uniqExact(who) FROM {ev}",
             desc="Prijavljeni po računu, gosti po uređaju. Gost koji se kasnije prijavio broji se kao taj korisnik."),
        stat("Novih", f"SELECT countIf(first_ts >= $__fromTime) FROM {first} WHERE who IN (SELECT who FROM {ev})",
             desc="Prvi događaj ikad je u odabranom razdoblju."),
        stat("Povratnih", f"SELECT countIf(first_ts < $__fromTime) FROM {first} WHERE who IN (SELECT who FROM {ev})"),
        stat("Prijavljenih", f"SELECT uniqExactIf(who, user_id != '') FROM {ev}"),
        stat("Sesija", f"SELECT uniqExact(session_id) FROM {ev}"),
        stat("Sesija po korisniku", f"SELECT round(uniqExact(session_id) / greatest(uniqExact(who), 1), 1) FROM {ev}"),
        table("Svi korisnici",
              "SELECT who AS korisnik,"
              " if(maxIf(user_id, user_id != '') != '', 'prijavljen', 'gost') AS racun,"
              " f.first_ts AS prvi_put, max(ts) AS zadnji_put,"
              " uniqExact(session_id) AS sesija,"
              " uniqExact(toDate(ts, 'Europe/Zagreb')) AS aktivnih_dana,"
              " countIf(event = 'screen_view') AS ekrana,"
              " uniqExactIf(video_id, video_id != '') AS epizoda,"
              " uniqExact(device_id) AS uredaja,"
              " arrayStringConcat(groupUniqArray(platform), ', ') AS platforme,"
              " anyLast(country) AS drzava, anyLast(city) AS grad,"
              " domainWithoutWWW(argMinIf(JSONExtractString(props, 'referrer'), ts, event = 'session_start')) AS prvi_izvor"
              f" FROM {ev} AS x LEFT JOIN {first} AS f USING who"
              " GROUP BY who, f.first_ts ORDER BY zadnji_put DESC LIMIT 2000",
              w=24, h=22, desc="Klik na korisnika otvara profil: sve sesije i događaje. Stupci se filtriraju ikonom u zaglavlju."),
    ], time="now-30d", desc="Popis korisnika s osnovnim brojkama; ulaz u profil korisnika.")


# --- 3. Korisnik (profil) ---------------------------------------------------------

def korisnik():
    allu = f"analytics.events WHERE {USER}"
    tr = f"{USER} AND $__timeFilter(ts)"
    st = screen_time(tr)
    hours = ", ".join(f"countIf(toHour(ts, 'Europe/Zagreb') = {h}) AS `{h:02d}`" for h in range(24))
    var = query_var(
        "who", "Korisnik ili uređaj",
        f"SELECT who FROM (SELECT {WHO} AS who, max(ts) AS l FROM analytics.events WHERE {APP} AND ts > now() - INTERVAL 90 DAY GROUP BY who ORDER BY l DESC LIMIT 1000)",
    )
    return dashboard("domovina-korisnik", "Korisnik", [
        text("Upiši ili odaberi **user_id** (Supabase) ili **device_id** gosta. Gostujući događaji s uređaja na kojima se korisnik "
             "kasnije prijavio pridružuju se njemu. Profil gore je za cijelu povijest; sesije i događaji poštuju odabrano razdoblje.", h=2),
        stat("Račun", f"SELECT if(countIf(user_id != '') > 0, 'prijavljen', 'gost') AS racun FROM {allu}", w=3, text=True),
        stat("Prvi put", f"SELECT formatDateTime(min(ts), '%d.%m.%Y. %H:%i', 'Europe/Zagreb') AS prvi FROM {allu}", w=4, text=True),
        stat("Zadnji put", f"SELECT formatDateTime(max(ts), '%d.%m.%Y. %H:%i', 'Europe/Zagreb') AS zadnji FROM {allu}", w=4, text=True),
        stat("Sesija", f"SELECT uniqExact(session_id) FROM {allu}", w=3),
        stat("Aktivnih dana", f"SELECT uniqExact(toDate(ts, 'Europe/Zagreb')) FROM {allu}", w=3),
        stat("Vrijeme u aplikaciji", f"SELECT sum(dwell_s) FROM {screen_time(USER)}", w=4, unit="dtdurations",
             desc="Procjena iz razmaka između događaja (najviše 5 min po razmaku)."),
        stat("Epizoda", f"SELECT uniqExactIf(video_id, video_id != '') FROM {allu}", w=3),
        table("Uređaji",
              "SELECT device_id, platform, anyLast(browser) AS preglednik, anyLast(os) AS os, anyLast(app_version) AS verzija,"
              " anyLast(locale) AS jezik, any(concat(toString(screen_w), '×', toString(screen_h))) AS ekran,"
              " anyLast(country) AS drzava, anyLast(city) AS grad, min(ts) AS prvi_put, max(ts) AS zadnji_put, uniqExact(session_id) AS sesija"
              f" FROM {allu} GROUP BY device_id, platform ORDER BY zadnji_put DESC",
              w=24, h=5, filterable=False),
        timeseries("Aktivnost po danu",
                   f"SELECT toStartOfDay(ts, 'Europe/Zagreb') AS time, event, count() AS n FROM analytics.events WHERE {tr} GROUP BY time, event ORDER BY time",
                   w=12, h=8, bars=True, stack=True),
        table("Kada je aktivan (dan u tjednu × sat)",
              f"SELECT ['pon','uto','sri','čet','pet','sub','ned'][toDayOfWeek(ts, 0, 'Europe/Zagreb')] AS dan, {hours}"
              f" FROM analytics.events WHERE {tr} GROUP BY toDayOfWeek(ts, 0, 'Europe/Zagreb') AS d, dan ORDER BY d",
              w=12, h=8, heat={"cols": "^\\d\\d$", "width": 30}, filterable=False),
        table("Sesije",
              "SELECT session_id AS sesija, min(ts) AS pocetak, sum(dwell_s) AS trajanje,"
              " countIf(event = 'screen_view') AS ekrana, uniqExactIf(vid, vid != '') AS epizoda,"
              " argMinIf(route, ts, event = 'screen_view') AS ulaz,"
              " domainWithoutWWW(anyIf(JSONExtractString(props, 'referrer'), event = 'session_start')) AS izvor,"
              " any(platform) AS platforma, anyLast(country) AS drzava,"
              " toUnixTimestamp64Milli(min(ts)) - 60000 AS od_ms, toUnixTimestamp64Milli(max(ts)) + 60000 AS do_ms"
              f" FROM {st} GROUP BY session_id ORDER BY pocetak DESC LIMIT 500",
              w=24, h=10, desc="Klik na sesiju otvara njezin tijek. Trajanje je procjena iz razmaka između događaja."),
        table("Epizode koje je otvorio",
              "SELECT vid AS epizoda, sum(dwell_s) AS na_ekranu, countIf(event = 'screen_view') AS otvaranja, min(ts) AS prvi_put, max(ts) AS zadnji_put"
              f" FROM {st} WHERE vid != '' GROUP BY vid ORDER BY zadnji_put DESC",
              w=12, h=10),
        table("Kanali i osobe",
              "SELECT if(ch != '', 'kanal', 'osoba') AS vrsta, if(ch != '', ch, person) AS slug, sum(dwell_s) AS na_ekranu, countIf(event = 'screen_view') AS otvaranja, max(ts) AS zadnji_put"
              f" FROM {st} WHERE ch != '' OR person != '' GROUP BY vrsta, slug ORDER BY zadnji_put DESC",
              w=12, h=10),
        table("Svi događaji",
              "SELECT ts AS vrijeme_dogadaja, event, route AS ruta, video_id, channel AS kanal, platform, session_id AS sesija, props,"
              " toUnixTimestamp64Milli(ts) - 600000 AS od_ms, toUnixTimestamp64Milli(ts) + 600000 AS do_ms"
              f" FROM analytics.events WHERE {tr} ORDER BY ts DESC LIMIT 2000",
              w=24, h=16),
    ], time="now-90d", refresh="", variables=[var], desc="Profil jednog korisnika: uređaji, sesije, epizode i svi događaji.")


# --- 4. Sesija ------------------------------------------------------------------

def sesija():
    s = f"{APP} AND session_id = ${{session:sqlstring}}"
    st = screen_time(s)
    var = query_var(
        "session", "Sesija",
        f"SELECT session_id FROM (SELECT session_id, max(ts) AS l FROM analytics.events WHERE {APP} AND ts > now() - INTERVAL 7 DAY GROUP BY session_id ORDER BY l DESC LIMIT 500)",
    )
    return dashboard("domovina-sesija", "Sesija", [
        table("Tko", "SELECT " + WHO.replace("user_id", "maxIf(user_id, user_id != '')").replace("device_id", "any(device_id)", 1)
              + " AS korisnik, any(platform) AS platforma, any(browser) AS preglednik, any(os) AS os, any(app_version) AS verzija,"
              " any(country) AS drzava, any(city) AS grad,"
              " domainWithoutWWW(anyIf(JSONExtractString(props, 'referrer'), event = 'session_start')) AS izvor,"
              " anyIf(JSONExtractString(props, 'utm_source'), event = 'session_start') AS utm_source"
              f" FROM analytics.events WHERE {s}",
              w=24, h=3, filterable=False),
        stat("Početak", f"SELECT formatDateTime(min(ts), '%d.%m.%Y. %H:%i:%S', 'Europe/Zagreb') AS pocetak FROM analytics.events WHERE {s}", w=6, text=True),
        stat("Trajanje", f"SELECT sum(dwell_s) FROM {st}", w=6, unit="dtdurations", desc="Procjena iz razmaka između događaja."),
        stat("Ekrana", f"SELECT countIf(event = 'screen_view') FROM analytics.events WHERE {s}", w=6),
        stat("Događaja", f"SELECT count() FROM analytics.events WHERE {s}", w=6),
        state_timeline("Ekrani kroz vrijeme",
                       f"SELECT ts AS time, if(event = 'app_background', '(pozadina)', screen) AS ekran FROM {st} ORDER BY ts",
                       h=5, desc="Vremenska crta ekrana; razdoblje dashboarda je postavljeno na trajanje sesije."),
        table("Tijek",
              "SELECT ts AS vrijeme_dogadaja,"
              " formatDateTime(toDateTime(dateDiff('second', min(ts) OVER (), ts), 'UTC'), '+%H:%i:%S') AS od_pocetka,"
              " event, screen AS ekran, dwell_s AS na_ekranu, video_id, props"
              f" FROM {st} ORDER BY ts",
              w=24, h=18, filterable=False),
    ], time="now-24h", refresh="", variables=[var], desc="Tijek jedne sesije, događaj po događaj.")


# --- 5. Sadržaj ------------------------------------------------------------------

def sadrzaj():
    tr = f"{APP} AND $__timeFilter(ts)"
    st = screen_time(tr)
    sv = f"analytics.events WHERE {tr} AND event = 'screen_view'"
    return dashboard("domovina-sadrzaj", "Sadržaj", [
        stat("Otvorenih epizoda", f"SELECT countIf(video_id != '') FROM {sv}"),
        stat("Različitih epizoda", f"SELECT uniqExactIf(video_id, video_id != '') FROM {sv}"),
        stat("Gledatelja epizoda", f"SELECT uniqExactIf({WHO}, video_id != '') FROM {sv}"),
        stat("Vrijeme na epizodama", f"SELECT sumIf(dwell_s, vid != '') FROM {st}", unit="dtdurations",
             desc="Procjena iz razmaka između događaja dok je epizoda na ekranu."),
        stat("Na epizodi po gledatelju", f"SELECT sumIf(dwell_s, vid != '') / greatest(uniqExactIf({WHO}, vid != ''), 1) FROM {st}", unit="dtdurations"),
        stat("Prikaza ekrana", f"SELECT count() FROM {sv}"),
        timeseries("Otvaranja po vrsti ekrana",
                   f"SELECT $__timeInterval(ts) AS time, {SCREEN_KIND} AS vrsta, count() AS n FROM {sv} GROUP BY time, vrsta ORDER BY time",
                   w=24, h=8, bars=True, stack=True),
        table("Epizode",
              "SELECT vid AS epizoda, countIf(event = 'screen_view') AS otvaranja, uniqExact(" + WHO + ") AS gledatelja,"
              " sum(dwell_s) AS vrijeme_ukupno, round(sum(dwell_s) / greatest(uniqExact(" + WHO + "), 1)) AS vrijeme_po_korisniku,"
              " max(ts) AS zadnji_put"
              f" FROM {st} WHERE vid != '' GROUP BY vid ORDER BY otvaranja DESC LIMIT 200",
              w=12, h=14, sort="otvaranja", desc="Klik na ID otvara epizodu na domovina.ai."),
        table("Kanali",
              "SELECT ch AS kanal, countIf(event = 'screen_view') AS otvaranja, uniqExact(" + WHO + ") AS posjetitelja, sum(dwell_s) AS vrijeme_ukupno"
              f" FROM {st} WHERE ch != '' GROUP BY ch ORDER BY otvaranja DESC LIMIT 100",
              w=12, h=7),
        table("Osobe",
              "SELECT person AS osoba, countIf(event = 'screen_view') AS otvaranja, uniqExact(" + WHO + ") AS posjetitelja, sum(dwell_s) AS vrijeme_ukupno"
              f" FROM {st} WHERE person != '' GROUP BY person ORDER BY otvaranja DESC LIMIT 100",
              w=12, h=7),
        table("Svi ekrani",
              "SELECT screen AS ruta, countIf(event = 'screen_view') AS otvaranja, uniqExact(" + WHO + ") AS posjetitelja,"
              " sum(dwell_s) AS vrijeme_ukupno, round(sum(dwell_s) / greatest(countIf(event = 'screen_view'), 1)) AS vrijeme"
              f" FROM {st} WHERE screen != '' GROUP BY screen ORDER BY otvaranja DESC LIMIT 300",
              w=24, h=12, desc="„vrijeme” je prosjek po otvaranju."),
    ], time="now-7d", desc="Epizode, kanali, osobe i ekrani: otvaranja, gledatelji i vrijeme na ekranu.")


# --- 6. Rast i zadržavanje ----------------------------------------------------------

def rast():
    allev = stitched(APP)
    tr_ev = stitched(f"{APP} AND $__timeFilter(e.ts)")
    weeks = ", ".join(
        f"if(w0 + INTERVAL {k} WEEK <= toMonday(today()), round(100 * countIf(has(ws, w0 + INTERVAL {k} WEEK)) / count(), 1), NULL) AS `T{k}`"
        for k in range(1, 13)
    )
    hours = ", ".join(f"countIf(toHour(ts, 'Europe/Zagreb') = {h}) AS `{h:02d}`" for h in range(24))
    firsts = f"(SELECT who, min(ts) AS first_ts, argMinIf(JSONExtractString(props, 'referrer'), ts, event = 'session_start') AS ref, argMinIf(JSONExtractString(props, 'utm_source'), ts, event = 'session_start') AS utm, argMin(platform, ts) AS plat, argMin(country, ts) AS drz FROM {allev} GROUP BY who)"
    return dashboard("domovina-rast", "Rast i zadržavanje", [
        stat("DAU (danas)", f"SELECT uniqExact({WHO}) FROM analytics.events WHERE {APP} AND toDate(ts, 'Europe/Zagreb') = today()"),
        stat("WAU (7 dana)", f"SELECT uniqExact({WHO}) FROM analytics.events WHERE {APP} AND ts > now() - INTERVAL 7 DAY"),
        stat("MAU (30 dana)", f"SELECT uniqExact({WHO}) FROM analytics.events WHERE {APP} AND ts > now() - INTERVAL 30 DAY"),
        stat("Ljepljivost DAU/MAU",
             f"SELECT round(100 * avg(d) / greatest((SELECT uniqExact({WHO}) FROM analytics.events WHERE {APP} AND ts > now() - INTERVAL 30 DAY), 1), 1)"
             f" FROM (SELECT toDate(ts, 'Europe/Zagreb') AS day, uniqExact({WHO}) AS d FROM analytics.events WHERE {APP} AND ts > now() - INTERVAL 30 DAY GROUP BY day)",
             unit="percent", desc="Prosječni dnevni korisnici kroz mjesečne, zadnjih 30 dana. 20 % znači da se prosječni korisnik vraća 6 dana u mjesecu."),
        stat("Novih u razdoblju", f"SELECT count() FROM {firsts} WHERE $__timeFilter(first_ts)"),
        stat("Vratilo se (od novih)",
             f"SELECT round(100 * countIf(days > 1) / greatest(count(), 1), 1) FROM (SELECT who, uniqExact(toDate(ts, 'Europe/Zagreb')) AS days, min(ts) AS f FROM {allev} GROUP BY who) WHERE $__timeFilter(f)",
             unit="percent", desc="Novi korisnici iz razdoblja koji su bili aktivni barem još jedan dan."),
        timeseries("Dnevno aktivni po platformi",
                   f"SELECT toStartOfDay(ts, 'Europe/Zagreb') AS time, platform, uniqExact({WHO}) AS korisnika FROM analytics.events WHERE {APP} AND $__timeFilter(ts) GROUP BY time, platform ORDER BY time",
                   w=12, h=8, bars=True, stack=True),
        timeseries("Novi i povratni po danu",
                   "SELECT toStartOfDay(ts, 'Europe/Zagreb') AS time,"
                   " uniqExactIf(who, toDate(f.first_ts, 'Europe/Zagreb') = toDate(ts, 'Europe/Zagreb')) AS novi,"
                   " uniqExactIf(who, toDate(f.first_ts, 'Europe/Zagreb') < toDate(ts, 'Europe/Zagreb')) AS povratni"
                   f" FROM {tr_ev} AS x LEFT JOIN {firsts} AS f USING who GROUP BY time ORDER BY time",
                   w=12, h=8, bars=True, stack=True),
        table("Zadržavanje po tjednim kohortama (%)",
              f"SELECT formatDateTime(w0, '%d.%m.%Y.') AS kohorta, count() AS novih, {weeks}"
              f" FROM (SELECT who, min(toMonday(ts, 'Europe/Zagreb')) AS w0, groupUniqArray(toMonday(ts, 'Europe/Zagreb')) AS ws FROM {allev} GROUP BY who)"
              " WHERE w0 >= toMonday(today() - INTERVAL 12 WEEK) GROUP BY w0 ORDER BY w0 DESC",
              w=24, h=10, heat={"cols": "^T\\d+$", "unit": "percent", "max": 100, "width": 60}, filterable=False,
              desc="Red = tjedan prvog dolaska. T1 = postotak koji je bio aktivan tjedan kasnije, T2 dva tjedna kasnije… Prazne ćelije su tjedni koji još nisu prošli."),
        table("Odakle dolaze novi korisnici",
              "SELECT if(ref = '', '(izravno)', domainWithoutWWW(ref)) AS izvor, utm AS utm_source, count() AS novih,"
              " round(100 * countIf(r.days > 1) / count(), 1) AS vratilo_se_pct"
              f" FROM {firsts} AS f LEFT JOIN (SELECT who, uniqExact(toDate(ts, 'Europe/Zagreb')) AS days FROM {allev} GROUP BY who) AS r USING who"
              " WHERE $__timeFilter(first_ts) GROUP BY izvor, utm_source ORDER BY novih DESC LIMIT 100",
              w=12, h=10, desc="Izvor prve sesije i koliko se njih vratilo barem još jedan dan."),
        table("Novi po platformi i državi",
              f"SELECT plat AS platforma, drz AS drzava, count() AS novih FROM {firsts} WHERE $__timeFilter(first_ts) GROUP BY plat, drz ORDER BY novih DESC LIMIT 100",
              w=12, h=10),
        table("Kada su svi aktivni (dan u tjednu × sat)",
              f"SELECT ['pon','uto','sri','čet','pet','sub','ned'][toDayOfWeek(ts, 0, 'Europe/Zagreb')] AS dan, {hours}"
              f" FROM analytics.events WHERE {APP} AND $__timeFilter(ts) AND event = 'screen_view' GROUP BY toDayOfWeek(ts, 0, 'Europe/Zagreb') AS d, dan ORDER BY d",
              w=24, h=8, heat={"cols": "^\\d\\d$", "width": 40}, filterable=False,
              desc="Broj otvorenih ekrana po danu u tjednu i satu (Zagreb)."),
    ], time="now-30d", refresh="5m", desc="Aktivni korisnici, novi i povratni, kohortno zadržavanje i izvori.")


# --- 7. Lijevci i putanje --------------------------------------------------------------

def lijevci():
    tr = f"{APP} AND $__timeFilter(ts)"
    st = screen_time(tr)
    sv = f"analytics.events WHERE {tr} AND event = 'screen_view'"
    paths = (
        f"SELECT session_id, ts, {SCREEN_KIND} AS kind,"
        " lagInFrame(" + SCREEN_KIND + ", 1, '(ulaz)') OVER (PARTITION BY session_id ORDER BY ts ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) AS prev"
        f" FROM {sv}"
    )
    return dashboard("domovina-lijevci", "Lijevci i putanje", [
        funnel("Lijevak sesije",
               "SELECT count() AS `1. sesija`, countIf(ep > 0) AS `2. otvorio epizodu`,"
               " countIf(ep_s >= 60) AS `3. minuta na epizodi`, countIf(ep_s >= 300) AS `4. 5 minuta na epizodi`,"
               " countIf(ep_s >= 300 AND eps >= 2) AS `5. i druga epizoda`"
               " FROM (SELECT session_id, countIf(event = 'screen_view' AND vid != '') AS ep, sumIf(dwell_s, vid != '') AS ep_s,"
               f" uniqExactIf(vid, vid != '') AS eps FROM {st} GROUP BY session_id)",
               w=12, h=9, desc="Sesije u razdoblju i koliko ih je stiglo do svakog koraka (svaki uključuje prethodne). Vrijeme na epizodi je procjena."),
        funnel("Lijevak korisnika",
               "SELECT count() AS `1. došao`, countIf(ep > 0) AS `2. otvorio epizodu`, countIf(ep > 0 AND days >= 2) AS `3. vratio se drugi dan`,"
               " countIf(ep > 0 AND days >= 3) AS `4. aktivan 3+ dana`, countIf(ep > 0 AND days >= 3 AND logged) AS `5. i prijavljen`"
               " FROM (SELECT who, uniqExactIf(video_id, video_id != '') AS ep, uniqExact(toDate(ts, 'Europe/Zagreb')) AS days, countIf(user_id != '') > 0 AS logged"
               f" FROM {stitched(APP)} GROUP BY who HAVING min(ts) >= $__fromTime AND min(ts) <= $__toTime)",
               w=12, h=9, desc="Korisnici kojima je prvi dolazak u razdoblju; svaki korak uključuje prethodne. Dani nakon razdoblja se računaju."),
        table("Ulazni ekrani",
              f"SELECT route AS ruta, count() AS sesija FROM (SELECT session_id, argMin(route, ts) AS route FROM {sv} GROUP BY session_id) GROUP BY route ORDER BY sesija DESC LIMIT 50",
              w=8, h=10, desc="Prvi ekran sesije."),
        table("Izlazni ekrani",
              f"SELECT route AS ruta, count() AS sesija FROM (SELECT session_id, argMax(route, ts) AS route FROM {sv} GROUP BY session_id) GROUP BY route ORDER BY sesija DESC LIMIT 50",
              w=8, h=10, desc="Zadnji ekran sesije: odavde odlaze."),
        table("Sesije s jednim ekranom (odbijanje)",
              f"SELECT route AS ruta, countIf(n = 1) AS samo_taj, count() AS ulaza, round(100 * samo_taj / ulaza, 1) AS odbijanje_pct"
              f" FROM (SELECT session_id, argMin(route, ts) AS route, count() AS n FROM {sv} GROUP BY session_id) GROUP BY route HAVING ulaza >= 1 ORDER BY ulaza DESC LIMIT 50",
              w=8, h=10, desc="Postotak sesija koje su ušle na ovaj ekran i nisu otvorile ni jedan drugi."),
        barchart("Najčešći prijelazi",
                 f"SELECT concat(prev, '  →  ', kind) AS prijelaz, count() AS n FROM ({paths}) WHERE prev != kind GROUP BY prijelaz ORDER BY n DESC LIMIT 25",
                 x="prijelaz", w=12, h=14, horizontal=True),
        table("Prijelazi (s → na)",
              f"SELECT prev AS s, kind AS na, count() AS n, round(100 * n / sum(n) OVER (PARTITION BY prev), 1) AS udio_pct"
              f" FROM ({paths}) WHERE prev != kind GROUP BY prev, kind ORDER BY s, n DESC",
              w=12, h=14, desc="Za svaki ekran: kamo korisnici idu dalje i u kojem udjelu. ID-jevi su zamijenjeni s „…”."),
        table("Najčešći putevi kroz sesiju",
              f"SELECT arrayStringConcat(arraySlice(arrayFilter((x, i) -> i = 1 OR x != path[i - 1], path, arrayEnumerate(path)), 1, 6), '  →  ') AS put, count() AS sesija"
              f" FROM (SELECT session_id, arrayMap(t -> t.2, arraySort(t -> t.1, groupArray((ts, {SCREEN_KIND})))) AS path FROM {sv} GROUP BY session_id)"
              " GROUP BY put ORDER BY sesija DESC LIMIT 50",
              w=24, h=12, desc="Prvih šest ekrana sesije (uzastopna ponavljanja spojena)."),
    ], time="now-7d", refresh="5m", desc="Gdje korisnici odustaju i kako se kreću kroz aplikaciju.")


# --- 8. Sponzori ----------------------------------------------------------------------

def sponzori():
    sp = f"analytics.events WHERE {APP} AND $__timeFilter(ts) AND event LIKE 'sponsored_%'"
    return dashboard("domovina-sponzori", "Sponzori", [
        stat("Prikaza", f"SELECT countIf(event = 'sponsored_impression') FROM {sp}", w=4),
        stat("Odslušano do kraja", f"SELECT countIf(event = 'sponsored_play_through') FROM {sp}", w=4),
        stat("Klikova", f"SELECT countIf(event = 'sponsored_click') FROM {sp}", w=4),
        stat("Do kraja / prikaz", f"SELECT round(100 * countIf(event = 'sponsored_play_through') / greatest(countIf(event = 'sponsored_impression'), 1), 1) FROM {sp}", w=4, unit="percent"),
        stat("Klik / prikaz (CTR)", f"SELECT round(100 * countIf(event = 'sponsored_click') / greatest(countIf(event = 'sponsored_impression'), 1), 2) FROM {sp}", w=4, unit="percent"),
        stat("Jedinstvenih slušatelja", f"SELECT uniqExactIf({WHO}, event = 'sponsored_impression') FROM {sp}", w=4),
        timeseries("Po danu",
                   f"SELECT toStartOfDay(ts, 'Europe/Zagreb') AS time, event, count() AS n FROM {sp} GROUP BY time, event ORDER BY time",
                   w=24, h=8, bars=True),
        table("Po brendu i slotu",
              "SELECT JSONExtractString(props, 'brand') AS brend, JSONExtractString(props, 'slot_key') AS slot,"
              " countIf(event = 'sponsored_impression') AS prikaza, uniqExactIf(" + WHO + ", event = 'sponsored_impression') AS slusatelja,"
              " countIf(event = 'sponsored_play_through') AS do_kraja, countIf(event = 'sponsored_click') AS klikova,"
              " round(100 * do_kraja / greatest(prikaza, 1), 1) AS do_kraja_pct, round(100 * klikova / greatest(prikaza, 1), 2) AS ctr_pct"
              f" FROM {sp} GROUP BY brend, slot ORDER BY prikaza DESC",
              w=24, h=10),
        table("Po epizodi",
              "SELECT video_id, JSONExtractString(props, 'brand') AS brend, countIf(event = 'sponsored_impression') AS prikaza,"
              " countIf(event = 'sponsored_play_through') AS do_kraja, countIf(event = 'sponsored_click') AS klikova"
              f" FROM {sp} GROUP BY video_id, brend ORDER BY prikaza DESC LIMIT 200",
              w=24, h=10),
    ], time="now-30d", refresh="5m", desc="Plaćeni sponzorski trenuci: prikazi, odslušano do kraja, klikovi.")


# --- 9. Zdravlje -------------------------------------------------------------------------

KNOWN = ["session_start", "screen_view", "heartbeat", "app_background", "identify", "sign_out",
         "sponsored_impression", "sponsored_play_through", "sponsored_click"]


def zdravlje():
    tr = f"$__timeFilter(ts)"
    known = ", ".join(f"'{e}'" for e in KNOWN)
    lag = "dateDiff('millisecond', ts, received_at)"
    return dashboard("domovina-zdravlje", "Zdravlje sustava", [
        stat("Događaja", f"SELECT count() FROM analytics.events WHERE {tr}"),
        stat("Kašnjenje p50", f"SELECT quantile(0.5)({lag}) FROM analytics.events WHERE {tr}", unit="ms",
             desc="Od događaja na klijentu do prijema na Workeru. Klijent šalje batch najviše svakih 30 s."),
        stat("Kašnjenje p95", f"SELECT quantile(0.95)({lag}) FROM analytics.events WHERE {tr}", unit="ms"),
        stat("Heartbeat po sesiji", f"SELECT round(countIf(event = 'heartbeat') / greatest(uniqExact(session_id), 1), 2) FROM analytics.events WHERE {APP} AND {tr}",
             desc="Dok je aplikacija u prednjem planu i nema drugih događaja, klijent šalje heartbeat svakih 30 s. Blizu nule znači da heartbeat ne radi, pa „online sada” podbacuje."),
        stat("Nepoznatih događaja", f"SELECT countIf(event NOT IN ({known})) FROM analytics.events WHERE {tr}"),
        stat("Bez verzije / platforme", f"SELECT countIf(app_version = '' OR platform = 'unknown') FROM analytics.events WHERE {tr}"),
        timeseries("Događaji po vrsti",
                   f"SELECT $__timeInterval(ts) AS time, event, count() AS n FROM analytics.events WHERE {tr} GROUP BY time, event ORDER BY time",
                   w=24, h=8, bars=True, stack=True),
        timeseries("Kašnjenje prijema (p50, p95)",
                   f"SELECT $__timeInterval(ts) AS time, quantile(0.5)({lag}) AS p50, quantile(0.95)({lag}) AS p95 FROM analytics.events WHERE {tr} GROUP BY time ORDER BY time",
                   w=12, h=8, unit="ms"),
        timeseries("Uređaji po verziji aplikacije",
                   f"SELECT toStartOfDay(ts, 'Europe/Zagreb') AS time, concat(platform, ' ', app_version) AS verzija, uniqExact(device_id) AS uredaja FROM analytics.events WHERE {APP} AND {tr} GROUP BY time, verzija ORDER BY time",
                   w=12, h=8, bars=True, stack=True),
        table("Po aplikaciji, platformi i verziji",
              f"SELECT app, platform, app_version AS verzija, count() AS dogadaja, uniqExact(device_id) AS uredaja, max(ts) AS zadnji,"
              f" quantile(0.5)({lag}) AS kasnjenje_p50, quantile(0.95)({lag}) AS kasnjenje_p95"
              f" FROM analytics.events WHERE {tr} GROUP BY app, platform, verzija ORDER BY dogadaja DESC",
              w=12, h=10),
        table("Nepoznati i testni događaji",
              f"SELECT event, app, count() AS n, min(ts) AS prvi, max(ts) AS zadnji, any(props) AS primjer_props"
              f" FROM analytics.events WHERE {tr} AND event NOT IN ({known}) GROUP BY event, app ORDER BY zadnji DESC",
              w=12, h=10, desc="Događaji koji nisu u docs/ugovor.md: novi događaj bez dokumentacije ili testni probe."),
        table("Sat klijenta izvan reda",
              f"SELECT platform, browser, os, count() AS n, round(avg({lag}) / 1000) AS prosjek_s"
              f" FROM analytics.events WHERE {tr} AND abs({lag}) > 120000 GROUP BY platform, browser, os ORDER BY n DESC LIMIT 50",
              w=24, h=7, desc="Događaji čije se vrijeme na klijentu razlikuje od prijema za više od 2 min (offline red ili pogrešan sat)."),
    ], time="now-24h", refresh="1m", desc="Radi li ingest: protok, kašnjenje, verzije, nepoznati događaji.")


DASHBOARDS = {
    "pregled": pregled,
    "korisnici": korisnici,
    "korisnik": korisnik,
    "sesija": sesija,
    "sadrzaj": sadrzaj,
    "rast": rast,
    "lijevci": lijevci,
    "sponzori": sponzori,
    "zdravlje": zdravlje,
}


def fill_macros(sql, who="", session=""):
    """Grafana makroi → ClickHouse, za provjeru upita izvan Grafane."""
    sql = sql.replace("${who:sqlstring}", "'" + who + "'").replace("${session:sqlstring}", "'" + session + "'")
    sql = re.sub(r"\$__timeFilter\(([^)]+)\)", r"\1 >= now() - INTERVAL 30 DAY AND \1 <= now()", sql)
    sql = re.sub(r"\$__timeInterval\(([^)]+)\)", r"toStartOfInterval(\1, INTERVAL 1 HOUR)", sql)
    sql = sql.replace("$__fromTime", "(now() - INTERVAL 30 DAY)").replace("$__toTime", "now()")
    return sql


if __name__ == "__main__":
    if "--sql" in sys.argv:
        who, session = sys.argv[2], sys.argv[3]
        for name, fn in DASHBOARDS.items():
            d = fn()
            for v in d["templating"]["list"]:
                print(f"-- {name} / var {v['name']}\n{fill_macros(v['query'], who, session)} FORMAT Null;")
            for p in d["panels"]:
                for t in p.get("targets", []):
                    print(f"-- {name} / {p['title']}\n{fill_macros(t['rawSql'], who, session)} FORMAT Null;")
        sys.exit(0)
    for name, fn in DASHBOARDS.items():
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(fn(), ensure_ascii=False, indent=2) + "\n")
        print(path.relative_to(OUT.parent.parent.parent))

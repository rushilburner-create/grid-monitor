"""
GRID Monitor — Data Ingestion Script
Pulls: commodity prices, EIA grid status, RSS news feeds, official commentary
Outputs: data/live.json (read by the dashboard)
"""

import json
import os
import re
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# ── CONFIG ──────────────────────────────────────────────────────────────────
with open("config.json") as f:
    cfg = json.load(f)

AV_KEY  = cfg["alpha_vantage_key"]
EIA_KEY = cfg["eia_key"]

# ── HELPERS ──────────────────────────────────────────────────────────────────
def fetch(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GRID-Monitor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8")
    except Exception as e:
        print(f"  FETCH ERROR {url[:60]}: {e}")
        return None

def fetch_json(url):
    raw = fetch(url)
    if raw:
        try:
            return json.loads(raw)
        except:
            return None
    return None

def now_utc():
    return datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")

# ── 1. COMMODITY PRICES (Alpha Vantage) ──────────────────────────────────────
# AV free tier: 25 calls/day. We fetch 9 symbols — fine for daily/15min refresh.
# Symbols mapped to display names and units
COMMODITY_SYMBOLS = [
    # (av_symbol, display_name, unit, prefix)
    ("BZ=F",  "Brent Crude",     "USD/bbl",    "$"),
    ("CL=F",  "WTI",             "USD/bbl",    "$"),
    ("NG=F",  "Henry Hub",       "USD/MMBtu",  "$"),
    ("TTF=F", "TTF Gas",         "EUR/MWh",    "€"),
    ("EUAFUT","EU ETS Carbon",   "EUR/t CO₂",  "€"),
    ("UX=F",  "Uranium",         "USD/lb",     "$"),
]

# For power/equity prices we use a separate batch call
EQUITY_TICKERS = ["NEE", "XOM", "CVX", "BP", "SHEL", "TTE", "TSLA", "ENPH", "ON", "WOLF"]

def fetch_prices():
    prices = []

    # Commodity quotes via AV global quote
    for sym, name, unit, prefix in COMMODITY_SYMBOLS:
        url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={sym}&apikey={AV_KEY}"
        data = fetch_json(url)
        if data and "Global Quote" in data and data["Global Quote"].get("05. price"):
            q = data["Global Quote"]
            price = float(q["05. price"])
            chg_pct = float(q["10. change percent"].replace("%",""))
            prices.append({
                "name": name,
                "value": f"{prefix}{price:,.2f}",
                "unit": unit,
                "change_pct": round(chg_pct, 2),
                "up": chg_pct >= 0
            })
            time.sleep(1)  # AV rate limit
        else:
            # Fallback placeholder so dashboard doesn't break
            prices.append({"name": name, "value": "N/A", "unit": unit, "change_pct": 0, "up": True})

    # Power prices — these aren't on AV, use hardcoded until we add a power API
    # These will be replaced by EIA data below where available
    prices.append({"name": "UK Power",        "value": "£74.10", "unit": "GBP/MWh",   "change_pct": 2.1,  "up": True,  "source": "manual"})
    prices.append({"name": "JKM LNG",         "value": "$13.85", "unit": "USD/MMBtu", "change_pct": 0.7,  "up": True,  "source": "manual"})
    prices.append({"name": "ERCOT Day-Ahead", "value": "$42.10", "unit": "USD/MWh",   "change_pct": -1.1, "up": False, "source": "manual"})

    return prices

# ── 2. EIA GRID STATUS ───────────────────────────────────────────────────────
# EIA API v2 — real-time grid data by region
# Docs: https://www.eia.gov/opendata/

EIA_REGIONS = [
    {
        "name": "ERCOT (Texas)",
        "eia_id": "TEX",
        "peak": 76.2,
        "status_thresholds": {"surplus": 0.88, "tight": 0.95}
    },
    {
        "name": "PJM (NE US)",
        "eia_id": "PJM",
        "peak": 168.2,
        "status_thresholds": {"surplus": 0.80, "tight": 0.92}
    },
    {
        "name": "MISO (Midwest)",
        "eia_id": "MISO",
        "peak": 120.0,
        "status_thresholds": {"surplus": 0.80, "tight": 0.92}
    },
    {
        "name": "CAISO (California)",
        "eia_id": "CAL",
        "peak": 52.0,
        "status_thresholds": {"surplus": 0.78, "tight": 0.90}
    },
]

def fetch_grid_status():
    regions = []

    for r in EIA_REGIONS:
        # EIA real-time demand endpoint
        url = (
            f"https://api.eia.gov/v2/electricity/rto/region-data/data/"
            f"?api_key={EIA_KEY}"
            f"&frequency=hourly"
            f"&data[0]=value"
            f"&facets[respondent][]={r['eia_id']}"
            f"&facets[type][]=D"   # D = demand
            f"&sort[0][column]=period&sort[0][direction]=desc"
            f"&length=1"
        )
        data = fetch_json(url)

        demand = None
        if data and "response" in data and data["response"].get("data"):
            try:
                demand = float(data["response"]["data"][0]["value"]) / 1000  # MW → GW
            except:
                pass

        # Fetch generation mix
        mix_url = (
            f"https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"
            f"?api_key={EIA_KEY}"
            f"&frequency=hourly"
            f"&data[0]=value"
            f"&facets[respondent][]={r['eia_id']}"
            f"&sort[0][column]=period&sort[0][direction]=desc"
            f"&length=10"
        )
        mix_data = fetch_json(mix_url)

        sources = {}
        if mix_data and "response" in mix_data and mix_data["response"].get("data"):
            total = 0
            raw = {}
            for item in mix_data["response"]["data"]:
                ftype = item.get("fueltype", "Other")
                val = float(item.get("value", 0))
                raw[ftype] = val
                total += val
            if total > 0:
                fuel_map = {
                    "NG": "Gas", "NUC": "Nuclear", "COL": "Coal",
                    "WND": "Wind", "SUN": "Solar", "WAT": "Hydro",
                    "OIL": "Oil", "OTH": "Other", "UNK": "Other"
                }
                for k, v in raw.items():
                    label = fuel_map.get(k, k)
                    pct = round((v / total) * 100)
                    if pct > 0:
                        sources[label] = f"{pct}%"

        # Determine status
        if demand:
            pct_of_peak = demand / r["peak"]
            if pct_of_peak < r["status_thresholds"]["surplus"]:
                status = "surplus"
            elif pct_of_peak < r["status_thresholds"]["tight"]:
                status = "tight"
            else:
                status = "stress"
            supply = demand * 1.04  # approximate, EIA doesn't expose supply directly
        else:
            demand = 0
            supply = 0
            status = "surplus"

        regions.append({
            "name": r["name"],
            "demand": round(demand, 1),
            "peak": r["peak"],
            "supply": round(supply, 1),
            "status": status,
            "sources": sources if sources else {"Gas": "N/A"},
            "drivers": []  # drivers are contextual — populated by rules below
        })

        time.sleep(0.5)

    # Add ENTSO-E Europe as a static fallback (ENTSO-E API requires separate registration)
    regions.append({
        "name": "ENTSO-E (Central EU)",
        "demand": 284.6,
        "peak": 320.0,
        "supply": 298.4,
        "status": "surplus",
        "sources": {"Gas": "28%", "Nuclear": "22%", "Wind": "18%", "Coal": "14%", "Hydro": "12%", "Solar": "6%"},
        "drivers": [
            {"label": "French nuclear -8GW", "type": "demand-up"},
            {"label": "DE wind surplus",     "type": "demand-dn"},
            {"label": "Cross-border flows ↑","type": "neutral"},
        ],
        "note": "ENTSO-E data — updated manually. Register at transparency.entsoe.eu for live feed."
    })

    return regions

# ── 3. RSS FEED PARSER ───────────────────────────────────────────────────────

SIGNAL_FEEDS = [
    # (url, default_type, default_tags)
    ("https://feeds.reuters.com/reuters/businessNews",        "mkt",  [{"t":"Global","c":"geo"}]),
    ("https://www.eia.gov/rss/news.xml",                      "pol",  [{"t":"USA","c":"geo"},{"t":"EIA","c":"co"}]),
    ("https://www.ferc.gov/news-events/news/rss.xml",         "pol",  [{"t":"USA","c":"geo"},{"t":"FERC","c":"co"}]),
    ("https://www.iea.org/rss/news.xml",                      "pol",  [{"t":"Global","c":"geo"},{"t":"IEA","c":"co"}]),
    ("https://www.ogj.com/rss/home.rss",                      "mkt",  [{"t":"Oil & Gas","c":"sec"}]),
    ("https://www.spglobal.com/commodityinsights/en/rss-feed/oil",  "mkt", [{"t":"Global","c":"geo"}]),
    ("https://www.pjm.com/media/news-room/press-releases.aspx", "pol",[{"t":"USA","c":"geo"},{"t":"PJM","c":"co"}]),
]

COMMENTARY_FEEDS = [
    ("https://www.ferc.gov/news-events/news/rss.xml",         "ferc", "FERC"),
    ("https://www.iea.org/rss/news.xml",                      "iea",  "IEA"),
    ("https://www.energy.gov/news",                            "gov",  "US DOE"),
]

# Keywords that make an item energy-relevant
ENERGY_KEYWORDS = [
    "energy","power","electricity","grid","solar","wind","nuclear","gas","oil",
    "lng","pipeline","refinery","utility","renewable","hydrogen","carbon","emissions",
    "battery","storage","transmission","capacity","demand","supply","fuel","barrel",
    "megawatt","gigawatt","ferc","eia","opec","iea","petroleum","crude","offshore",
    "ev","electric vehicle","semiconductor","inverter","charging","lithium",
    "tesla","nextera","exxon","shell","bp","chevron","totalenergies",
]

# Tag rules — if headline contains keyword, add tag
TAG_RULES = [
    (["usa","u.s.","american","ferc","eia","doe","texas","california","pjm","ercot","miso"],
     {"t":"USA","c":"geo"}),
    (["europe","eu","european","germany","france","uk","britain","norway","entsoe","ofgem"],
     {"t":"Europe","c":"geo"}),
    (["canada","canadian","alberta","trans mountain"],
     {"t":"Canada","c":"geo"}),
    (["solar","wind","renewable","clean energy","hydrogen","battery","storage","green"],
     {"t":"Renewables","c":"sec"}),
    (["nuclear","uranium","reactor","vogtle","smr"],
     {"t":"Nuclear","c":"sec"}),
    (["oil","crude","brent","wti","barrel","upstream","e&p","exploration"],
     {"t":"Oil","c":"sec"}),
    (["gas","lng","natural gas","pipeline","midstream","ttf","henry hub"],
     {"t":"Gas","c":"sec"}),
    (["refin","downstream","crack spread"],
     {"t":"Refiners","c":"sec"}),
    (["grid","transmission","interconnect","capacity market","demand response"],
     {"t":"Grid","c":"sec"}),
    (["ev","electric vehicle","charging","tesla","rivian","lucid"],
     {"t":"EV","c":"sec"}),
    (["semiconductor","chip","inverter","power electronics","silicon carbide","sic","gan","wolfspeed","onsemi","infineon"],
     {"t":"Power Semi","c":"sec"}),
    (["merger","acquisition","deal","takeover","buys","acquires","billion"],
     {"t":"M&A","c":"pol"}),
    (["policy","regulation","rule","legislation","congress","parliament","directive","mandate"],
     {"t":"Policy","c":"pol"}),
]

def classify_type(text):
    t = text.lower()
    if any(w in t for w in ["acqui","merger","takeover","buys","deal","joint venture"]):
        return "deal"
    if any(w in t for w in ["alert","emergency","outage","storm","crisis","shortage","blackout"]):
        return "alr"
    if any(w in t for w in ["policy","regulation","rule","law","directive","mandate","congress","parliament"]):
        return "pol"
    if any(w in t for w in ["pipeline","plant","project","construction","commission","capacity addition","offshore"]):
        return "inf"
    return "mkt"

TYPE_ICONS = {"pol":"⚖️","mkt":"📊","inf":"🏗️","alr":"⚡","deal":"💰","com":"🏛️"}
IMP_RULES = {
    "h": ["emergency","alert","crisis","blackout","outage","shutdown","major","billion","record"],
    "m": ["deal","acqui","merger","policy","regulation","capacity","project","agreement"],
}

def calc_impact(text):
    t = text.lower()
    if any(w in t for w in IMP_RULES["h"]): return "h"
    if any(w in t for w in IMP_RULES["m"]): return "m"
    return "l"

def auto_tag(text, base_tags):
    tags = list(base_tags)
    t = text.lower()
    seen = {tg["t"] for tg in tags}
    for keywords, tag in TAG_RULES:
        if any(kw in t for kw in keywords) and tag["t"] not in seen:
            tags.append(tag)
            seen.add(tag["t"])
            if len(tags) >= 4:
                break
    return tags

def is_energy_relevant(text):
    t = text.lower()
    return any(kw in t for kw in ENERGY_KEYWORDS)

def parse_rss(url, base_tags, max_items=4):
    raw = fetch(url)
    if not raw:
        return []

    items = []
    try:
        # Strip namespaces for easier parsing
        raw_clean = re.sub(r'\s+xmlns[^"]*"[^"]*"', '', raw)
        root = ET.fromstring(raw_clean)
    except:
        return []

    channel = root.find("channel")
    if channel is None:
        channel = root

    count = 0
    for item in channel.findall("item"):
        if count >= max_items:
            break
        title_el = item.find("title")
        pub_el   = item.find("pubDate")
        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        pub   = pub_el.text.strip()   if pub_el   is not None and pub_el.text   else ""

        if not title or not is_energy_relevant(title):
            continue

        # Format time
        try:
            dt = datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S")
            time_str = dt.strftime("%H:%M\n%d %b")
        except:
            time_str = "Recent"

        item_type = classify_type(title)
        tags      = auto_tag(title, base_tags)
        impact    = calc_impact(title)

        items.append({
            "time":      time_str,
            "icon":      item_type,
            "iconLabel": TYPE_ICONS.get(item_type, "📰"),
            "head":      title,
            "tags":      tags,
            "imp":       impact,
            "type":      item_type,
        })
        count += 1

    return items

def fetch_signals():
    all_items = []
    for url, dtype, base_tags in SIGNAL_FEEDS:
        print(f"  Fetching signals: {url[:50]}...")
        items = parse_rss(url, base_tags)
        all_items.extend(items)
        time.sleep(0.5)
    # Deduplicate by headline
    seen = set()
    unique = []
    for item in all_items:
        if item["head"] not in seen:
            seen.add(item["head"])
            unique.append(item)
    return unique[:20]  # cap at 20 items

def fetch_commentary():
    items = []
    for url, source_type, source_name in COMMENTARY_FEEDS:
        print(f"  Fetching commentary: {url[:50]}...")
        raw_items = parse_rss(url, [{"t": source_name, "c": "pol"}], max_items=3)
        for item in raw_items:
            item["type"]   = source_type
            item["icon"]   = "com"
            item["iconLabel"] = "🏛️"
            item["speaker"]   = source_name
            item["role"]      = {
                "ferc": "Federal Energy Regulatory Commission",
                "iea":  "International Energy Agency",
                "gov":  "US Department of Energy",
                "pjm":  "PJM Interconnection",
            }.get(source_type, source_name)
        items.extend(raw_items)
        time.sleep(0.5)
    return items[:12]

# ── 4. EQUITY SUBSECTORS (static until Cap IQ CSV lands) ────────────────────
# This will be replaced by Cap IQ data in Week 2.
# Format is identical to what the Cap IQ parser will produce,
# so the dashboard doesn't need to change — just swap the source.

def load_equity_data():
    capiq_path = "data/capiq.json"
    if os.path.exists(capiq_path):
        with open(capiq_path) as f:
            print("  Loading Cap IQ data from data/capiq.json")
            return json.load(f)

    # Fallback: placeholder data
    print("  No Cap IQ data found — using placeholder equity data")
    return [
        {"name":"Oil E&P",       "sub":"Upstream · GICS 10102010",        "mktcap":"$1.84T","pe":"8.2x","data":{"price":{"ytd":"-4.2%","y1":"+11.3%","y3":"+38.7%"},"eps":{"ytd":"-2.1%","y1":"+3.4%","y3":"+18.2%"},"pe":{"ytd":"-0.8x","y1":"+1.2x","y3":"+3.4x"},"ev":{"ytd":"-0.4x","y1":"+0.9x","y3":"+2.1x"}},"spark":[30,45,38,52,40,35,28]},
        {"name":"Midstream",     "sub":"Pipelines/MLPs · GICS 10102030",   "mktcap":"$620B", "pe":"14.8x","data":{"price":{"ytd":"+2.1%","y1":"+9.4%","y3":"+24.3%"},"eps":{"ytd":"+1.4%","y1":"+5.2%","y3":"+12.8%"},"pe":{"ytd":"+0.3x","y1":"+1.8x","y3":"+2.6x"},"ev":{"ytd":"+0.2x","y1":"+1.1x","y3":"+1.9x"}},"spark":[45,48,50,52,49,51,53]},
        {"name":"LNG",           "sub":"Export/Import · GICS 10102030",    "mktcap":"$340B", "pe":"11.4x","data":{"price":{"ytd":"+1.3%","y1":"+14.2%","y3":"+52.1%"},"eps":{"ytd":"+4.8%","y1":"+12.3%","y3":"+34.5%"},"pe":{"ytd":"-0.2x","y1":"+0.8x","y3":"+4.2x"},"ev":{"ytd":"+0.1x","y1":"+1.3x","y3":"+3.8x"}},"spark":[40,42,48,55,52,58,61]},
        {"name":"Refiners",      "sub":"Downstream · GICS 10102040",       "mktcap":"$280B", "pe":"6.9x", "data":{"price":{"ytd":"-6.8%","y1":"-3.2%","y3":"+12.4%"},"eps":{"ytd":"-11.2%","y1":"-8.4%","y3":"+4.3%"},"pe":{"ytd":"-1.2x","y1":"-0.8x","y3":"+1.2x"},"ev":{"ytd":"-0.6x","y1":"-0.4x","y3":"+0.8x"}},"spark":[60,55,48,42,38,32,28]},
        {"name":"Oil Services",  "sub":"Field Services · GICS 10102050",   "mktcap":"$520B", "pe":"13.1x","data":{"price":{"ytd":"-3.4%","y1":"+6.8%","y3":"+44.2%"},"eps":{"ytd":"+2.1%","y1":"+8.4%","y3":"+22.6%"},"pe":{"ytd":"-0.4x","y1":"+1.4x","y3":"+3.8x"},"ev":{"ytd":"-0.2x","y1":"+1.0x","y3":"+2.4x"}},"spark":[50,48,52,55,50,48,46]},
        {"name":"Utilities",     "sub":"Electric · GICS 55105010",         "mktcap":"$1.12T","pe":"16.4x","data":{"price":{"ytd":"+3.8%","y1":"+12.4%","y3":"+18.2%"},"eps":{"ytd":"+2.8%","y1":"+6.4%","y3":"+14.3%"},"pe":{"ytd":"+0.6x","y1":"+2.1x","y3":"+1.8x"},"ev":{"ytd":"+0.4x","y1":"+1.4x","y3":"+1.2x"}},"spark":[40,42,45,48,52,55,58]},
        {"name":"Renewables",    "sub":"Solar/Wind · GICS 20106020",       "mktcap":"$890B", "pe":"22.8x","data":{"price":{"ytd":"+8.4%","y1":"+24.8%","y3":"+62.4%"},"eps":{"ytd":"+12.3%","y1":"+28.4%","y3":"+84.2%"},"pe":{"ytd":"+1.8x","y1":"+4.2x","y3":"+8.6x"},"ev":{"ytd":"+1.2x","y1":"+3.1x","y3":"+6.4x"}},"spark":[20,28,35,42,52,62,74]},
        {"name":"Nuclear",       "sub":"Operators/Fuel · GICS 55105010",   "mktcap":"$210B", "pe":"18.2x","data":{"price":{"ytd":"+6.2%","y1":"+38.4%","y3":"+142.8%"},"eps":{"ytd":"+8.4%","y1":"+22.6%","y3":"+68.4%"},"pe":{"ytd":"+1.4x","y1":"+5.8x","y3":"+12.4x"},"ev":{"ytd":"+0.8x","y1":"+3.4x","y3":"+8.2x"}},"spark":[15,18,25,35,48,62,80]},
        {"name":"Grid & Storage","sub":"T&D, Battery · GICS 20106010",     "mktcap":"$380B", "pe":"24.4x","data":{"price":{"ytd":"+11.2%","y1":"+32.4%","y3":"+88.6%"},"eps":{"ytd":"+9.8%","y1":"+24.2%","y3":"+56.4%"},"pe":{"ytd":"+2.2x","y1":"+5.4x","y3":"+10.8x"},"ev":{"ytd":"+1.4x","y1":"+3.8x","y3":"+7.2x"}},"spark":[22,28,36,45,58,68,82]},
        {"name":"EV",            "sub":"Elec Vehicles · GICS 25102010",    "mktcap":"$780B", "pe":"34.2x","data":{"price":{"ytd":"+5.8%","y1":"+18.4%","y3":"+124.2%"},"eps":{"ytd":"+14.2%","y1":"+32.4%","y3":"+112.8%"},"pe":{"ytd":"+2.8x","y1":"+6.4x","y3":"+18.4x"},"ev":{"ytd":"+1.8x","y1":"+4.2x","y3":"+12.4x"}},"spark":[18,22,28,38,52,66,82]},
        {"name":"Power Semis",   "sub":"Power Electronics · GICS 45301020","mktcap":"$420B", "pe":"28.6x","data":{"price":{"ytd":"+9.2%","y1":"+28.4%","y3":"+96.4%"},"eps":{"ytd":"+11.4%","y1":"+24.8%","y3":"+72.4%"},"pe":{"ytd":"+2.4x","y1":"+5.2x","y3":"+14.8x"},"ev":{"ytd":"+1.6x","y1":"+3.6x","y3":"+9.8x"}},"spark":[20,24,32,44,58,72,88]},
    ]

# ── 5. MAIN ──────────────────────────────────────────────────────────────────
def main():
    print(f"\n{'='*60}")
    print(f"GRID Monitor — Ingestion run at {now_utc()}")
    print(f"{'='*60}")

    output = {"last_updated": now_utc()}

    print("\n[1/4] Fetching commodity prices...")
    output["prices"] = fetch_prices()
    print(f"  Got {len(output['prices'])} price entries")

    print("\n[2/4] Fetching EIA grid status...")
    output["grid"] = fetch_grid_status()
    print(f"  Got {len(output['grid'])} regions")

    print("\n[3/4] Fetching signal feed (RSS)...")
    output["signals"] = fetch_signals()
    print(f"  Got {len(output['signals'])} signal items")

    print("\n[4/4] Fetching commentary feed...")
    output["commentary"] = fetch_commentary()
    print(f"  Got {len(output['commentary'])} commentary items")

    print("\n[+] Loading equity data...")
    output["equity"] = load_equity_data()
    print(f"  Got {len(output['equity'])} subsectors")

    # Write output
    os.makedirs("data", exist_ok=True)
    with open("data/live.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✓ data/live.json written — {len(json.dumps(output))} bytes")
    print(f"✓ Done at {now_utc()}\n")

if __name__ == "__main__":
    main()

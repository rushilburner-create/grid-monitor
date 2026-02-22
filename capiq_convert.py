"""
GRID Monitor — Cap IQ CSV Converter
Run this on your work laptop after exporting from Capital IQ.
Converts the CSV exports into data/capiq.json which ingest.py picks up automatically.

Usage:
  python scripts/capiq_convert.py --folder C:/Users/YOU/Documents/GRID/capiq/

Expects files named:
  grid_ep.csv, grid_midstream.csv, grid_lng.csv, grid_refiners.csv,
  grid_oilservices.csv, grid_utilities.csv, grid_renewables.csv,
  grid_nuclear.csv, grid_gridstorage.csv, grid_ev.csv, grid_powersemi.csv
"""

import csv
import json
import os
import argparse
from datetime import datetime

SUBSECTOR_MAP = {
    "grid_ep.csv":          ("Oil E&P",        "Upstream · GICS 10102010"),
    "grid_midstream.csv":   ("Midstream",       "Pipelines/MLPs · GICS 10102030"),
    "grid_lng.csv":         ("LNG",             "Export/Import · GICS 10102030"),
    "grid_refiners.csv":    ("Refiners",        "Downstream · GICS 10102040"),
    "grid_oilservices.csv": ("Oil Services",    "Field Services · GICS 10102050"),
    "grid_utilities.csv":   ("Utilities",       "Electric · GICS 55105010"),
    "grid_renewables.csv":  ("Renewables",      "Solar/Wind · GICS 20106020"),
    "grid_nuclear.csv":     ("Nuclear",         "Operators/Fuel · GICS 55105010"),
    "grid_gridstorage.csv": ("Grid & Storage",  "T&D, Battery · GICS 20106010"),
    "grid_ev.csv":          ("EV",              "Elec Vehicles · GICS 25102010"),
    "grid_powersemi.csv":   ("Power Semis",     "Power Electronics · GICS 45301020"),
}

# Map Cap IQ column headers to our internal field names
# Adjust these if your Cap IQ export uses slightly different column names
COL_MAP = {
    "Market Capitalization":               "mktcap_raw",
    "P/E (NTM)":                           "pe_current",
    "EV/EBITDA (NTM)":                     "ev_current",
    "EPS (NTM Mean Estimate)":             "eps_ntm",
    "EPS (NTM Mean, 4 Weeks Prior)":       "eps_4w",
    "EPS (NTM Mean, 13 Weeks Prior)":      "eps_13w",
    "EPS (NTM Mean, 52 Weeks Prior)":      "eps_52w",
    "P/E (NTM, 52 Weeks Prior)":           "pe_52w",
    "EV/EBITDA (NTM, 52 Weeks Prior)":     "ev_52w",
    "Price % Change (YTD)":                "price_ytd",
    "Price % Change (1 Year)":             "price_1y",
    "Price % Change (3 Year)":             "price_3y",
}

def fmt_pct(val, suffix="%"):
    try:
        f = float(val)
        sign = "+" if f >= 0 else ""
        return f"{sign}{f:.1f}{suffix}"
    except:
        return "N/A"

def fmt_x(val):
    try:
        f = float(val)
        sign = "+" if f >= 0 else ""
        return f"{sign}{f:.1f}x"
    except:
        return "N/A"

def fmt_mktcap(val):
    try:
        # Cap IQ returns in millions USD
        m = float(str(val).replace(",",""))
        if m >= 1_000_000:
            return f"${m/1_000_000:.2f}T"
        elif m >= 1_000:
            return f"${m/1_000:.0f}B"
        else:
            return f"${m:.0f}M"
    except:
        return "N/A"

def median(vals):
    clean = []
    for v in vals:
        try:
            clean.append(float(str(v).replace(",","")))
        except:
            pass
    if not clean:
        return None
    clean.sort()
    mid = len(clean) // 2
    return clean[mid]

def process_file(filepath, name, sub):
    rows = []
    with open(filepath, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Normalise column names
            normed = {}
            for k, v in row.items():
                k_clean = k.strip()
                if k_clean in COL_MAP:
                    normed[COL_MAP[k_clean]] = v.strip()
            if normed:
                rows.append(normed)

    if not rows:
        print(f"  WARNING: No data rows in {filepath}")
        return None

    # Aggregate: market-cap weighted median for multiples, simple median for pcts
    def med(field):
        return median([r.get(field, "") for r in rows])

    mktcap_total = sum(
        float(str(r.get("mktcap_raw","0")).replace(",",""))
        for r in rows if r.get("mktcap_raw")
    )

    pe_cur  = med("pe_current")
    pe_52w  = med("pe_52w")
    ev_cur  = med("ev_current")
    ev_52w  = med("ev_52w")
    eps_ntm = med("eps_ntm")
    eps_4w  = med("eps_4w")
    eps_13w = med("eps_13w")
    eps_52w = med("eps_52w")

    # Calculate changes
    def pct_chg(new, old):
        try:
            return ((new - old) / abs(old)) * 100
        except:
            return None

    def x_chg(new, old):
        try:
            return new - old
        except:
            return None

    eps_rev_ytd  = pct_chg(eps_ntm, eps_13w)  # ~QTD as proxy for YTD
    eps_rev_1y   = pct_chg(eps_ntm, eps_52w)
    pe_chg_ytd   = x_chg(pe_cur, pe_52w) * 0.25 if pe_cur and pe_52w else None  # approximate YTD
    pe_chg_1y    = x_chg(pe_cur, pe_52w)
    ev_chg_ytd   = x_chg(ev_cur, ev_52w) * 0.25 if ev_cur and ev_52w else None
    ev_chg_1y    = x_chg(ev_cur, ev_52w)

    price_ytd = med("price_ytd")
    price_1y  = med("price_1y")
    price_3y  = med("price_3y")

    return {
        "name":   name,
        "sub":    f"{sub} · {len(rows)} cos",
        "mktcap": fmt_mktcap(mktcap_total),
        "pe":     f"{pe_cur:.1f}x" if pe_cur else "N/A",
        "data": {
            "price": {
                "ytd": fmt_pct(price_ytd),
                "y1":  fmt_pct(price_1y),
                "y3":  fmt_pct(price_3y),
            },
            "eps": {
                "ytd": fmt_pct(eps_rev_ytd),
                "y1":  fmt_pct(eps_rev_1y),
                "y3":  "N/A",
            },
            "pe": {
                "ytd": fmt_x(pe_chg_ytd),
                "y1":  fmt_x(pe_chg_1y),
                "y3":  "N/A",
            },
            "ev": {
                "ytd": fmt_x(ev_chg_ytd),
                "y1":  fmt_x(ev_chg_1y),
                "y3":  "N/A",
            },
        },
        "spark": [50, 50, 50, 50, 50, 50, 50],  # placeholder — real sparklines need price history
        "source": "capiq",
        "as_of":  datetime.now().strftime("%d %b %Y %H:%M"),
        "n_companies": len(rows),
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", default="capiq_exports", help="Folder containing Cap IQ CSV exports")
    parser.add_argument("--out",    default="data/capiq.json")
    args = parser.parse_args()

    folder = args.folder
    if not os.path.exists(folder):
        print(f"ERROR: Folder not found: {folder}")
        return

    results = []
    for filename, (name, sub) in SUBSECTOR_MAP.items():
        filepath = os.path.join(folder, filename)
        if not os.path.exists(filepath):
            print(f"  SKIP: {filename} not found")
            continue
        print(f"  Processing {filename}...")
        result = process_file(filepath, name, sub)
        if result:
            results.append(result)
            print(f"    → {result['name']}: {result['mktcap']}, {result['n_companies']} companies, P/E {result['pe']}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n✓ Wrote {len(results)} subsectors to {args.out}")

if __name__ == "__main__":
    main()

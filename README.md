# GRID — Energy & Power Monitor
### Setup Guide (Windows, no coding required)

---

## TONIGHT: Get live on Vercel + wire up real data

---

### STEP 1 — Upload to GitHub (10 mins)

1. Go to **github.com** and sign in as `rushilburner-create`
2. Click the **+** button top right → **New repository**
3. Name it: `grid-monitor`
4. Set to **Public**
5. Click **Create repository**
6. On the next screen, click **uploading an existing file**
7. Upload ALL the files in this folder, maintaining the folder structure:
   ```
   index.html
   config.json
   scripts/ingest.py
   scripts/capiq_convert.py
   .github/workflows/refresh.yml
   ```
   > Tip: You can drag the whole folder into the GitHub upload window
8. Commit message: `Initial upload`
9. Click **Commit changes**

---

### STEP 2 — Add your API keys as GitHub Secrets (5 mins)

Your keys never go in any file — they live securely in GitHub Secrets.

1. In your repo, click **Settings** (top menu)
2. Left sidebar → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add secret: Name = `AV_KEY`, Value = `DE0ZHI5XV9HHJ0C5`
5. Add secret: Name = `EIA_KEY`, Value = `nXBxzAy8Ev51rni0VoHkZEkVgaIm3K7V2xG27mEB`

---

### STEP 3 — Deploy to Vercel (5 mins)

1. Go to **vercel.com** and sign in
2. Click **Add New Project**
3. Click **Import Git Repository**
4. Connect your GitHub account if not already done
5. Select `grid-monitor`
6. Leave all settings as default
7. Click **Deploy**
8. Wait ~1 minute → you'll get a URL like `grid-monitor-abc123.vercel.app`

**That's your dashboard URL. Open it on any device.**

---

### STEP 4 — Point the dashboard at live data (2 mins)

Once GitHub Actions runs for the first time (it runs every 15 mins),
your data will live at:

```
https://raw.githubusercontent.com/rushilburner-create/grid-monitor/main/data/live.json
```

Update one line in `index.html` (line ~180):
```javascript
// Change this:
const DATA_URL = "data/live.json";

// To this:
const DATA_URL = "https://raw.githubusercontent.com/rushilburner-create/grid-monitor/main/data/live.json";
```

Edit directly on GitHub: open `index.html` → click the pencil icon → find that line → change it → commit.

Vercel will auto-redeploy within 30 seconds.

---

### STEP 5 — Trigger first data run (1 min)

1. In your GitHub repo, click **Actions** (top menu)
2. Click **GRID Monitor — Data Refresh**
3. Click **Run workflow** → **Run workflow**
4. Watch it run — takes about 2 minutes
5. When it finishes, you'll see `data/live.json` appear in your repo
6. Reload your Vercel URL — real data!

---

### STEP 6 — Verify everything is working

Your dashboard should now show:
- ✅ Live commodity prices (Alpha Vantage)
- ✅ Real EIA grid status for ERCOT, PJM, MISO, CAISO
- ✅ Live news from Reuters Energy, EIA, FERC, IEA, OGJ
- ✅ Official commentary from FERC, IEA, DOE RSS feeds
- ⏳ Equity table (placeholder until Cap IQ — see below)

GitHub Actions will refresh automatically every 15 minutes from now on.

---

## LATER THIS WEEK: Cap IQ financial data (work laptop)

### Cap IQ Screens to build and save

Go to **Screening → Company Screening** on Capital IQ website.
Build one screen per subsector using these GICS codes:

| File to export     | Subsector      | GICS Sub-Industry Code |
|--------------------|----------------|------------------------|
| grid_ep.csv        | Oil E&P        | 10102010               |
| grid_midstream.csv | Midstream      | 10102030               |
| grid_lng.csv       | LNG            | 10102030 (LNG cos)     |
| grid_refiners.csv  | Refiners       | 10102040               |
| grid_oilservices.csv | Oil Services | 10102050               |
| grid_utilities.csv | Utilities      | 55105010               |
| grid_renewables.csv | Renewables    | 20106020               |
| grid_nuclear.csv   | Nuclear        | 55105010 (nuclear cos) |
| grid_gridstorage.csv | Grid/Storage | 20106010               |
| grid_ev.csv        | EV             | 25102010               |
| grid_powersemi.csv | Power Semis    | 45301020               |

### Columns to add to each screen:

- Market Capitalization
- P/E (NTM)
- EV/EBITDA (NTM)
- EPS (NTM Mean Estimate)
- EPS (NTM Mean, 4 Weeks Prior)
- EPS (NTM Mean, 13 Weeks Prior)
- EPS (NTM Mean, 52 Weeks Prior)
- P/E (NTM, 52 Weeks Prior)
- EV/EBITDA (NTM, 52 Weeks Prior)
- Price % Change (YTD)
- Price % Change (1 Year)
- Price % Change (3 Year)

### Daily export routine (2 mins/day on work laptop):

1. Open each saved screen → Export → CSV
2. Name files exactly as shown in the table above
3. Put all CSVs in one folder, e.g. `C:\Users\YOU\Documents\GRID\capiq\`
4. Run: `python scripts/capiq_convert.py --folder C:\Users\YOU\Documents\GRID\capiq\`
5. This creates `data/capiq.json`
6. Upload `data/capiq.json` to your GitHub repo (drag and drop)
7. Dashboard auto-updates within minutes

---

## Cost summary

| Service         | Cost     |
|----------------|----------|
| Vercel          | Free     |
| GitHub          | Free     |
| Alpha Vantage   | Free     |
| EIA API         | Free     |
| RSS feeds       | Free     |
| Capital IQ      | You have access |
| **Total**       | **$0/mo** |

---

## Troubleshooting

**GitHub Actions failing?**
→ Check Actions tab → click the failed run → read the error log

**Dashboard showing placeholder data?**
→ Check that `data/live.json` exists in your repo
→ Check that DATA_URL in index.html points to the raw GitHub URL

**Prices showing N/A?**
→ Alpha Vantage free tier is 25 calls/day — check you haven't hit the limit
→ Regenerate key at alphavantage.co if needed

**Cap IQ converter failing?**
→ Check column names match exactly — Cap IQ sometimes adds spaces
→ Open the CSV in Excel and check the header row

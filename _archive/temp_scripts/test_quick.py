#!/usr/bin/env python3
"""Quick system test - validates actual return formats"""
import json, sys, os, traceback, sqlite3

os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
errors = []

def _safe(s): return str(s).encode("ascii", "replace").decode("ascii")
def ok(msg): print(f"  OK: {_safe(msg)}")
def ng(msg): print(f"  NG: {_safe(msg)}"); errors.append(str(msg))
def info(msg): print(f"  -- {_safe(msg)}")

# ── 1. Import ──────────────────────────────────────────────────────────────
print("\n=== 1. Import test ===")
try:
    import stock_mcp_server as s
    ok("stock_mcp_server")
except Exception as e:
    ng(f"import stock_mcp_server: {e}"); sys.exit(1)

try:
    import run_screen_full as r
    ok("run_screen_full")
except Exception as e:
    ng(f"import run_screen_full: {e}")

# ── 2. DB initialization ───────────────────────────────────────────────────
print("\n=== 2. DB initialization ===")
try:
    s._init_db()
    ok("price DB (_init_db)")
except Exception as e:
    ng(f"_init_db: {e}")

try:
    s._init_fins_db()
    ok("fins DB (_init_fins_db)")
except Exception as e:
    ng(f"_init_fins_db: {e}")

# ── 3. fetch_stock (returns human-readable string) ────────────────────────
print("\n=== 3. fetch_stock (Toyota 7203) ===")
try:
    result = s.fetch_stock("7203")
    if isinstance(result, str) and "7203" in result:
        ok(f"fetch_stock returned: {result[:80]}")
    else:
        ng(f"unexpected result: {repr(result[:80])}")
except Exception as e:
    ng(f"fetch_stock: {e}")

# ── 4. screen_stock (returns human-readable string) ────────────────────────
print("\n=== 4. screen_stock (Toyota 7203) ===")
try:
    result = s.screen_stock("7203")
    if isinstance(result, str) and len(result) > 10:
        lines = result.encode("utf-8", errors="replace").decode("utf-8")
        ok(f"screen_stock returned {len(result)} chars")
        info(lines[:150])
    else:
        ng(f"unexpected result: {repr(result[:80])}")
except Exception as e:
    ng(f"screen_stock: {e}")

# ── 5. yfinance fallback ───────────────────────────────────────────────────
print("\n=== 5. yfinance fallback (6758 Sony) ===")
try:
    bars = s._fetch_daily_yf("6758")
    if bars and len(bars) > 0:
        ok(f"{len(bars)} bars, last={bars[-1]['Date']} close={bars[-1]['C']}")
    elif bars is not None and len(bars) == 0:
        ng("yfinance returned empty list (might be network issue)")
    else:
        ng("yfinance returned None")
except Exception as e:
    ng(f"_fetch_daily_yf: {e}")

# ── 6. DB record count ─────────────────────────────────────────────────────
print("\n=== 6. DB record count ===")
try:
    base = os.environ.get("INVEST_BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base, "data", "stock_prices.db")
    if os.path.exists(db_path):
        con = sqlite3.connect(db_path)
        n_stocks = con.execute("SELECT COUNT(DISTINCT code) FROM daily_prices").fetchone()[0]
        n_rows = con.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
        con.close()
        ok(f"stock_prices.db: {n_stocks} stocks, {n_rows:,} rows")
        if n_stocks < 100:
            ng(f"Too few stocks in DB: {n_stocks} (expected 4000+)")
    else:
        ng(f"DB not found: {db_path}")
except Exception as e:
    ng(f"price DB count: {e}")

try:
    fins_path = os.path.join(base, "data", "fins_data.db")
    if os.path.exists(fins_path):
        con = sqlite3.connect(fins_path)
        # Check actual table name
        tables = [t[0] for t in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        info(f"fins tables: {tables}")
        if tables:
            tbl = tables[0]
            n_stocks = con.execute(f"SELECT COUNT(DISTINCT code) FROM {tbl}").fetchone()[0]
            n_rows = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            con.close()
            ok(f"fins_data.db: {n_stocks} stocks, {n_rows:,} rows in '{tbl}'")
        else:
            con.close()
            ng("fins_data.db has no tables yet (bulk_download_fins not run)")
    else:
        ng(f"fins DB not found: {fins_path}")
except Exception as e:
    ng(f"fins DB count: {e}")

# ── 7. screen_full_results.json ────────────────────────────────────────────
print("\n=== 7. screen_full_results.json ===")
try:
    base = os.environ.get("INVEST_BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
    rf = os.path.join(base, "data", "screen_full_results.json")
    if os.path.exists(rf):
        with open(rf) as f:
            results = json.load(f)
        if isinstance(results, dict):
            # Dict format: keyed by stock code or has 'results' key
            if "results" in results:
                items = results["results"]
                ok(f"dict with 'results' key: {len(items)} stocks")
            else:
                ok(f"dict with {len(results)} entries (codes as keys)")
                sample_key = list(results.keys())[0]
                sample = results[sample_key]
                info(f"sample keys: {list(sample.keys())[:6]}")
        elif isinstance(results, list):
            ok(f"{len(results)} stocks screened")
            if results:
                info(f"sample keys: {list(results[0].keys())[:6]}")
        else:
            ng(f"unexpected type: {type(results)}")
    else:
        ng(f"not found: {rf}")
except Exception as e:
    ng(f"screen_full_results: {e}")

# ── 8. export_chart_data ──────────────────────────────────────────────────
print("\n=== 8. export_chart_data ===")
try:
    result = s.export_chart_data()
    if isinstance(result, str) and "OK" in result:
        ok(f"export returned: {result[:100]}")
        # Also check the json file was written
        chart_json = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chart_data.json")
        if os.path.exists(chart_json):
            ok(f"chart_data.json exists ({os.path.getsize(chart_json):,} bytes)")
        else:
            ng("chart_data.json was not written")
    else:
        ng(f"unexpected result: {repr(result[:100])}")
except Exception as e:
    ng(f"export_chart_data: {e}")

# ── 9. RS calculation sanity check ────────────────────────────────────────
print("\n=== 9. RS calculation check ===")
try:
    base = os.environ.get("INVEST_BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
    rf = os.path.join(base, "data", "screen_full_results.json")
    if os.path.exists(rf):
        with open(rf) as f:
            results = json.load(f)

        items = results if isinstance(results, list) else (
            results.get("results", list(results.values()))
        )

        rs_fields = ["rs10w", "rs30w", "rs50w", "rs_10w", "rs_30w", "rs_50w"]
        found_fields = []
        sample = items[0] if items else {}
        for f_name in rs_fields:
            if f_name in sample:
                found_fields.append(f_name)

        if found_fields:
            ok(f"RS fields found: {found_fields}")
            # Check for obviously wrong values (should be around 1.0 for neutral)
            for f_name in found_fields:
                vals = [x[f_name] for x in items if isinstance(x, dict) and f_name in x and x[f_name] is not None]
                if vals:
                    import statistics
                    med = statistics.median(vals)
                    mn, mx = min(vals), max(vals)
                    ok(f"  {f_name}: min={mn:.3f} median={med:.3f} max={mx:.3f} (expect ~1.0 median)")
                    if med < 0.5 or med > 2.0:
                        ng(f"  {f_name} median {med:.3f} seems wrong (should be ~1.0)")
        else:
            ng(f"No RS fields found in results. Available: {list(sample.keys())[:10]}")
    else:
        info("screen_full_results.json not found, skip RS check")
except Exception as e:
    ng(f"RS check: {e}")

# ── 10. Task Scheduler ────────────────────────────────────────────────────
print("\n=== 10. Windows Task Scheduler ===")
try:
    import subprocess
    result = subprocess.run(
        ["powershell", "-Command",
         "Get-ScheduledTask -TaskPath '\\InvestSystem\\' 2>$null | "
         "Select-Object TaskName,State | ConvertTo-Json -Compress"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0 and result.stdout.strip():
        out = result.stdout.strip()
        try:
            tasks = json.loads(out)
            if not isinstance(tasks, list):
                tasks = [tasks]
            for t in tasks:
                state = {0:"Unknown",1:"Disabled",2:"Queued",3:"Ready",4:"Running"}.get(t.get("State",0), "?")
                ok(f"Task '{t.get('TaskName')}' = {state}")
        except:
            ok(f"Tasks found: {out[:100]}")
    else:
        ng(f"InvestSystem tasks not found (run setup_scheduler.ps1?)")
except Exception as e:
    ng(f"Task check: {e}")

# ── 11. .env check (existence only, not content) ───────────────────────────
print("\n=== 11. .env file check ===")
base = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(base, ".env")
if os.path.exists(env_path):
    size = os.path.getsize(env_path)
    ok(f".env exists ({size} bytes) - API keys configured")
else:
    ng(".env not found - create from .env.example and add API keys")

# ── Summary ────────────────────────────────────────────────────────────────
print(f"\n{'='*55}")
if errors:
    print(f"RESULT: {len(errors)} ISSUE(S) FOUND")
    for e in errors:
        # Truncate long error messages
        msg = e if len(e) < 100 else e[:97] + "..."
        print(f"  * {msg}")
    sys.exit(1)
else:
    print("RESULT: ALL TESTS PASSED")
    sys.exit(0)

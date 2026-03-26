"""
stock_mcp_server.py  v2.0
J-Quants stock analysis MCP server for personal investment dashboard
Target: 100M JPY by end of 2029 / Stage-2 growth stock concentration

Features:
  - Minervini Trend Template (7 conditions) full screening
  - Background thread execution (no MCP timeout)
  - ETF/REIT exclusion
  - RS (Relative Strength) vs Nikkei225: 6w / 13w / 26w
  - Fundamental data: sales / op-profit / net-profit / EPS
  - Portfolio management (holdings / P&L)
  - Watchlist management
  - Run-time metadata recorded in results
"""

import sqlite3
import subprocess
import os
import time
import json
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timedelta

import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("stock-analyzer")

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

BASE_DIR   = Path(r"C:\Users\yohei\Documents\invest-system")
DB_PATH    = BASE_DIR / "data" / "stock_prices.db"
CSV_DIR    = BASE_DIR / "csv_output"
CONFIG     = Path.home() / ".jquants_config.json"

PROGRESS_FILE  = BASE_DIR / "data" / "screen_full_progress.json"
RESULTS_FILE   = BASE_DIR / "data" / "screen_full_results.json"
MASTER_CACHE   = BASE_DIR / "data" / "equity_master_cache.json"
PORTFOLIO_FILE = BASE_DIR / "data" / "portfolio.json"
WATCHLIST_FILE = BASE_DIR / "data" / "watchlist.json"

GITHUB_DIR  = Path(r"C:\Users\yohei\Documents\invest-system-github")
CHART_DIR   = GITHUB_DIR / "charts"

MASTER_CACHE_TTL_DAYS = 7
BATCH_SIZE        = 50
BATCH_SLEEP_SEC   = 0.5
REQUEST_SLEEP_SEC = 0.1
MAX_RETRIES       = 3
RETRY_SLEEP_SEC   = 10.0
PARALLEL_WORKERS  = 5   # 並列APIリクエスト数（有料プラン向け）

# Nikkei225 ETF code used as benchmark for RS calculation
NIKKEI225_CODE = "1321"

# ETF / investment trust code prefixes (13xx - 19xx)
ETF_CODE_PREFIXES = ("13", "14", "15", "16", "17", "18", "19")

# Major stocks for screen_all
MAJOR_STOCKS = [
    "7203", "6758", "9984", "6861", "7974",
    "8306", "9433", "6954", "4502", "8035",
    "6367", "9432", "7267", "6501", "4063",
    "8411", "6702", "9022", "4568", "3382",
]

# ---------------------------------------------------------------------------
# Background job state
# ---------------------------------------------------------------------------

_job_lock  = threading.Lock()
_job_state = {
    "running":     False,
    "done":        0,
    "total":       0,
    "passed":      0,
    "errors":      0,
    "started_at":  None,
    "finished_at": None,
    "elapsed_min": None,
    "status":      "idle",
    "last_code":   "",
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    key = os.environ.get("JQUANTS_API_KEY", "")
    if key:
        return key
    if CONFIG.exists():
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
        return data.get("jquants_api_key", "")
    raise RuntimeError(
        "J-Quants API key not found. "
        "Create ~/.jquants_config.json with {\"jquants_api_key\": \"YOUR_KEY\"}"
    )

def _headers() -> dict:
    return {"x-api-key": _get_api_key()}

# ---------------------------------------------------------------------------
# DB init
# ---------------------------------------------------------------------------

def _init_db():
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "data").mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS weekly_prices (
            code TEXT, date TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (code, date)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS daily_prices (
            code TEXT, date TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (code, date)
        )
    """)
    con.commit()
    con.close()

def _save_weekly(code: str, df: pd.DataFrame):
    con = sqlite3.connect(DB_PATH)
    df_save = df.reset_index()
    df_save.columns = [c.lower() for c in df_save.columns]
    df_save["code"] = code
    df_save.to_sql("weekly_prices", con, if_exists="replace",
                   index=False, method="multi")
    con.close()

def _load_weekly(code: str) -> pd.DataFrame:
    con = sqlite3.connect(DB_PATH)
    df  = pd.read_sql(
        "SELECT * FROM weekly_prices WHERE code=? ORDER BY date",
        con, params=(code,)
    )
    con.close()
    return df


def _save_daily_db(code: str, df: pd.DataFrame):
    """Save daily OHLCV to SQLite (upsert / append, no data loss)."""
    _init_db()
    con = sqlite3.connect(DB_PATH)
    df_save = df.reset_index()
    df_save.columns = [c.lower() for c in df_save.columns]
    df_save["code"] = code
    df_save["date"] = df_save["date"].astype(str).str[:10]
    # INSERT OR REPLACE to merge new data with existing
    for _, row in df_save.iterrows():
        con.execute(
            "INSERT OR REPLACE INTO daily_prices "
            "(code, date, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (row["code"], row["date"],
             row["open"], row["high"], row["low"], row["close"], row["volume"]),
        )
    con.commit()
    con.close()


def _load_daily_db(code: str) -> pd.DataFrame:
    """Load daily OHLCV from SQLite (all historical data)."""
    _init_db()
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        "SELECT date, open, high, low, close, volume "
        "FROM daily_prices WHERE code=? ORDER BY date",
        con, params=(code,),
    )
    con.close()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return df

# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def _fetch_daily(code_4: str) -> list:
    """Fetch ~400 days of daily OHLCV from J-Quants V2."""
    code_5    = code_4 + "0"
    date_from = (datetime.now() - timedelta(days=400)).strftime("%Y%m%d")
    date_to   = datetime.now().strftime("%Y%m%d")
    url = (f"https://api.jquants.com/v2/equities/bars/daily"
           f"?code={code_5}&from={date_from}&to={date_to}")
    resp = requests.get(url, headers=_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json().get("data", [])

def _daily_to_weekly(bars: list) -> pd.DataFrame:
    df = pd.DataFrame(bars)
    df["date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("date").set_index("date")
    df["open"]   = df.get("AdjO", df["O"])
    df["high"]   = df.get("AdjH", df["H"])
    df["low"]    = df.get("AdjL", df["L"])
    df["close"]  = df.get("AdjC", df["C"])
    df["volume"] = df.get("AdjVo", df["Vo"])
    return df[["open","high","low","close","volume"]].resample("W-FRI").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()

def _daily_to_df(bars: list) -> pd.DataFrame:
    df = pd.DataFrame(bars)
    df["date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("date").set_index("date")
    df["open"]   = df.get("AdjO", df["O"])
    df["high"]   = df.get("AdjH", df["H"])
    df["low"]    = df.get("AdjL", df["L"])
    df["close"]  = df.get("AdjC", df["C"])
    df["volume"] = df.get("AdjVo", df["Vo"])
    return df[["open","high","low","close","volume"]]

# ---------------------------------------------------------------------------
# Minervini Trend Template (7 conditions, daily SMA 50/150/200)
# ---------------------------------------------------------------------------

def _minervini(daily_df: pd.DataFrame) -> dict:
    c = daily_df["close"].values.astype(float)
    if len(c) < 52:
        return {"error": f"only {len(c)} trading days (need >= 52)"}

    price     = c[-1]
    sma50     = c[-min(50,  len(c)):].mean()
    sma150    = c[-min(150, len(c)):].mean()
    sma200    = c[-min(200, len(c)):].mean()
    sma200_1m = c[-min(220, len(c)):-20].mean() if len(c) >= 30 else sma200 * 0.999
    high52    = c[-min(252, len(c)):].max()
    low52     = c[-min(252, len(c)):].min()

    cond = [
        bool(price > sma150 and price > sma200),   # 1
        bool(sma150 > sma200),                      # 2
        bool(sma200 > sma200_1m),                   # 3
        bool(sma50 > sma150 and sma50 > sma200),   # 4
        bool(price > sma50),                        # 5
        bool(price > low52 * 1.25),                 # 6
        bool(price > high52 * 0.75),                # 7
    ]
    n = sum(cond)
    return {
        "passed":     n >= 6,
        "score":      f"{n}/7",
        "conditions": cond,
        "price":      round(float(price), 1),
        "sma50":      round(float(sma50), 1),
        "sma150":     round(float(sma150), 1),
        "sma200":     round(float(sma200), 1),
        "high52":     round(float(high52), 1),
        "low52":      round(float(low52), 1),
        "days":       len(c),
    }

# ---------------------------------------------------------------------------
# RS (Relative Strength) vs Nikkei225
# ---------------------------------------------------------------------------

def _calc_rs(stock_closes: list, bench_closes: list) -> dict:
    """
    Calculate RS ratio vs benchmark over 6w / 13w / 26w.
    RS > 1.0 means outperforming the benchmark.
    """
    def _pct(arr, n):
        if len(arr) < n + 1:
            return None
        return arr[-1] / arr[-n-1] - 1.0

    s = stock_closes
    b = bench_closes

    rs6w  = (_pct(s, 6)  / _pct(b, 6)  if _pct(b, 6)  and _pct(b, 6)  != -1 else None)
    rs13w = (_pct(s, 13) / _pct(b, 13) if _pct(b, 13) and _pct(b, 13) != -1 else None)
    rs26w = (_pct(s, 26) / _pct(b, 26) if _pct(b, 26) and _pct(b, 26) != -1 else None)

    # Normalize: RS > 1.0 = outperform, convert to score-style (1.0 = market)
    def safe_round(v):
        return round(v, 3) if v is not None else None

    return {
        "rs6w":  safe_round(rs6w),
        "rs13w": safe_round(rs13w),
        "rs26w": safe_round(rs26w),
    }

# ---------------------------------------------------------------------------
# Fundamental data
# ---------------------------------------------------------------------------

def _fetch_fins(code_4: str) -> dict:
    """
    Fetch latest financial summary from /v2/fins/summary (V2 short field names).
    V2 field mapping: Sales/OP/NP/EPS/BPS/Eq/TA/FcstSales/FcstNP/FcstEPS
    Response key: "summary"
    """
    code_5 = code_4 + "0"
    url    = f"https://api.jquants.com/v2/fins/summary?code={code_5}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=30)
        resp.raise_for_status()
        # V2レスポンスキーは "data"
        items = resp.json().get("data", [])
        if not items:
            return {}
        # 通期(FY)の直近データを優先、なければ最新
        fy_items = [i for i in items if i.get("CurPerType") == "FY"]
        latest   = fy_items[-1] if fy_items else items[-1]

        def _num(v):
            if v is None or v == "": return None
            try: return float(v)
            except: return None

        return {
            "fiscal_year":     latest.get("CurFYEn", "")[:7],
            "period":          latest.get("CurPerType", ""),
            "disclosed_date":  latest.get("DiscDate", ""),
            "sales":           _num(latest.get("Sales")),
            "op_profit":       _num(latest.get("OP")),
            "ord_profit":      _num(latest.get("OdP")),
            "net_profit":      _num(latest.get("NP")),
            "eps":             _num(latest.get("EPS")),
            "bps":             _num(latest.get("BPS")),
            "equity":          _num(latest.get("Eq")),
            "total_assets":    _num(latest.get("TA")),
            "equity_ratio":    _num(latest.get("EqAR")),
            "forecast_sales":  _num(latest.get("FcstSales")),
            "forecast_profit": _num(latest.get("FcstNP")),
            "forecast_eps":    _num(latest.get("FcstEPS")),
            "div_annual":      _num(latest.get("DivAnn")),
        }
    except Exception:
        return {}

def _fetch_fins_history(code_4: str) -> list:
    """Fetch all financial records from J-Quants (FY + quarterly, ~10 years)."""
    code_5 = code_4 + "0"
    url = f"https://api.jquants.com/v2/fins/summary?code={code_5}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=30)
        resp.raise_for_status()
        items = resp.json().get("data", [])
    except Exception:
        return []

    def _num(v):
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    records = []
    for item in items:
        fy_end = item.get("CurFYEn", "")
        per_type = item.get("CurPerType", "")
        if not fy_end or not per_type:
            continue
        records.append({
            "fy": fy_end[:7],            # e.g. "2026-03"
            "period": per_type,           # FY, 1Q, 2Q, 3Q
            "date": item.get("DiscDate", ""),
            "sales": _num(item.get("Sales")),
            "op": _num(item.get("OP")),
            "np": _num(item.get("NP")),
            "eps": _num(item.get("EPS")),
            "bps": _num(item.get("BPS")),
            "div": _num(item.get("DivAnn")),
            "eq_ratio": _num(item.get("EqAR")),
            # Forecasts (current FY)
            "f_sales": _num(item.get("FSales")),
            "f_op": _num(item.get("FOP")),
            "f_np": _num(item.get("FNP")),
            "f_eps": _num(item.get("FEPS")),
            # Next FY forecasts
            "nf_sales": _num(item.get("NxFSales")),
            "nf_op": _num(item.get("NxFOP")),
            "nf_np": _num(item.get("NxFNp")),
            "nf_eps": _num(item.get("NxFEPS")),
        })
    return records


# ---------------------------------------------------------------------------
# ETF detection
# ---------------------------------------------------------------------------

def _is_etf(code_4: str, item: dict = None) -> bool:
    if str(code_4).startswith(ETF_CODE_PREFIXES):
        return True
    if item:
        tc        = str(item.get("TypeCode", ""))
        etf_types = {"ETF", "REIT", "ETN", "InfFund", "PRF"}
        if any(t.lower() in tc.lower() for t in etf_types):
            return True
    return False

# ---------------------------------------------------------------------------
# Equity master
# ---------------------------------------------------------------------------

def fetch_equity_master(force: bool = False) -> list:
    if not force and MASTER_CACHE.exists():
        cached    = json.loads(MASTER_CACHE.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(cached["fetched_at"])
        if datetime.now() - cached_at < timedelta(days=MASTER_CACHE_TTL_DAYS):
            return cached["items"]

    resp = requests.get("https://api.jquants.com/v2/equities/master",
                        headers=_headers(), timeout=30)
    resp.raise_for_status()
    data     = resp.json()
    items    = data.get("info", data.get("data", []))
    equities = [
        i for i in items
        if len(str(i.get("Code", ""))) == 5
        and str(i.get("Code", ""))[-1] == "0"
    ]
    (BASE_DIR / "data").mkdir(parents=True, exist_ok=True)
    MASTER_CACHE.write_text(
        json.dumps({"fetched_at": datetime.now().isoformat(),
                    "count": len(equities), "items": equities},
                   ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return equities

def _lookup_name(code_4: str) -> str:
    if not MASTER_CACHE.exists():
        return ""
    master = json.loads(MASTER_CACHE.read_text(encoding="utf-8"))
    code_5 = code_4 + "0"
    for item in master.get("items", []):
        if str(item.get("Code", "")) == code_5:
            # V2短縮形: CoNameEn / CoName、旧V1: CompanyNameEnglish / CompanyName
            return (item.get("CoNameEn")
                    or item.get("CoName")
                    or item.get("CompanyNameEnglish")
                    or item.get("CompanyName", ""))
    return ""
    return ""

# ---------------------------------------------------------------------------
# screen_full helpers
# ---------------------------------------------------------------------------

def _load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return {"last_index": 0, "started_at": None, "total": 0}

def _save_progress(index: int, total: int, started_at: str):
    PROGRESS_FILE.write_text(
        json.dumps({"last_index": index, "total": total,
                    "started_at": started_at}, ensure_ascii=False),
        encoding="utf-8"
    )

def _load_results() -> dict:
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    return {}

def _save_results(results: dict):
    RESULTS_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def _screen_one_with_retry(code_4: str, bench_closes: list = None) -> dict:
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(REQUEST_SLEEP_SEC)
            bars = _fetch_daily(code_4)
            if not bars or len(bars) < 10:
                return {"code": code_4, "error": "insufficient data"}

            daily_df = _daily_to_df(bars)
            result   = _minervini(daily_df)
            if "error" in result:
                return {"code": code_4, "error": result["error"]}

            # RS calculation
            rs = {}
            if bench_closes and len(bench_closes) > 26:
                stock_closes = daily_df["close"].tolist()
                rs = _calc_rs(stock_closes, bench_closes)

            return {
                "code":       code_4,
                "name":       _lookup_name(code_4),
                "price":      result["price"],
                "passed":     result["passed"],
                "score":      result["score"],
                "high52":     result["high52"],
                "low52":      result["low52"],
                "sma50":      result["sma50"],
                "sma150":     result["sma150"],
                "sma200":     result["sma200"],
                "conditions": result["conditions"],
                "rs6w":       rs.get("rs6w"),
                "rs13w":      rs.get("rs13w"),
                "rs26w":      rs.get("rs26w"),
            }

        except Exception as e:
            err = str(e)
            if "429" in err or "rate" in err.lower():
                time.sleep(RETRY_SLEEP_SEC * (attempt + 1))
            elif attempt == MAX_RETRIES - 1:
                return {"code": code_4, "error": err}
            else:
                time.sleep(RETRY_SLEEP_SEC)
    return {"code": code_4, "error": "max retries exceeded"}

# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _run_screen_full_bg(codes: list, total: int, resume: bool, started_at: str):
    global _job_state

    # Nikkei225ベンチマーク取得
    bench_closes = []
    try:
        bench_bars   = _fetch_daily(NIKKEI225_CODE)
        bench_df     = _daily_to_df(bench_bars)
        bench_closes = bench_df["close"].tolist()
    except Exception:
        pass

    results   = _load_results() if resume else {}
    start_idx = 0
    if resume:
        prog      = _load_progress()
        start_idx = prog.get("last_index", 0)

    errors = 0

    # 未処理コードのみ抽出
    pending = [c for c in codes[start_idx:]
               if not (c in results and not results[c].get("error"))]
    # 既処理分をカウントに反映
    already_done = total - len(pending) - start_idx + \
                   sum(1 for c in codes[start_idx:] if c in results and not results[c].get("error"))

    with _job_lock:
        _job_state["done"] = start_idx + (total - start_idx - len(pending))

    try:
        # ThreadPoolExecutorで並列処理
        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
            future_to_code = {
                executor.submit(_screen_one_with_retry, code, bench_closes): code
                for code in pending
            }

            batch_count = 0
            for future in as_completed(future_to_code):
                # 停止チェック
                with _job_lock:
                    if not _job_state["running"]:
                        executor.shutdown(wait=False)
                        _save_results(results)
                        return

                code = future_to_code[future]
                try:
                    res = future.result()
                except Exception as e:
                    res = {"code": code, "error": str(e)}

                results[code] = res
                batch_count  += 1

                with _job_lock:
                    _job_state["done"]     += 1
                    _job_state["last_code"] = code
                    if res.get("error"):
                        errors += 1
                        _job_state["errors"] = errors
                    elif res.get("passed"):
                        _job_state["passed"] += 1

                # BATCH_SIZE件ごとに保存
                if batch_count % BATCH_SIZE == 0:
                    done_count = _job_state["done"]
                    _save_progress(done_count, total, started_at)
                    _save_results(results)

        # 完了
        _save_progress(total, total, started_at)
        finished_at = datetime.now().isoformat()
        elapsed_min = round(
            (datetime.now() - datetime.fromisoformat(started_at)).total_seconds() / 60, 1
        )
        pass_count = sum(1 for k, v in results.items()
                         if k != "__meta__" and v.get("passed"))

        results["__meta__"] = {
            "started_at":  started_at,
            "finished_at": finished_at,
            "elapsed_min": elapsed_min,
            "total":       total,
            "passed":      pass_count,
            "errors":      errors,
        }
        _save_results(results)

        with _job_lock:
            _job_state.update({
                "running":     False,
                "status":      "complete",
                "finished_at": finished_at,
                "elapsed_min": elapsed_min,
            })

    except Exception as e:
        with _job_lock:
            _job_state["running"] = False
            _job_state["status"]  = f"error: {e}"

    except Exception as e:
        with _job_lock:
            _job_state["running"] = False
            _job_state["status"]  = f"error: {e}"

# ---------------------------------------------------------------------------
# ============================================================
# MCP TOOLS
# ============================================================
# ---------------------------------------------------------------------------

# ── 1. 株価取得 ──────────────────────────────────────────────

@mcp.tool()
def fetch_stock(code: str) -> str:
    """
    Fetch stock price data from J-Quants API and save to DB/CSV.
    Example: fetch_stock("6758")
    """
    _init_db()
    try:
        bars = _fetch_daily(code)
        if not bars:
            return f"ERROR {code}: no data returned"

        weekly    = _daily_to_weekly(bars)
        _save_weekly(code, weekly)
        (CSV_DIR / f"{code}_weekly.csv").write_text(
            weekly.reset_index().to_csv(index=False), encoding="utf-8"
        )
        daily_df = _daily_to_df(bars)
        (CSV_DIR / f"{code}_daily.csv").write_text(
            daily_df.reset_index().to_csv(index=False), encoding="utf-8"
        )
        last_close = daily_df["close"].iloc[-1]
        return (f"OK {code}: {len(bars)} daily -> {len(weekly)} weekly, "
                f"last close: {last_close:.0f}")
    except Exception as e:
        return f"ERROR {code}: {e}"


@mcp.tool()
def screen_stock(code: str) -> str:
    """
    Apply Minervini trend template + RS to a single stock.
    Example: screen_stock("6758")
    """
    daily_csv = CSV_DIR / f"{code}_daily.csv"
    if daily_csv.exists():
        df = pd.read_csv(daily_csv, parse_dates=["date"]).set_index("date")
    else:
        df = _load_weekly(code)
        if df.empty:
            return f"No data for {code}. Run fetch_stock first."
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").set_index("date")

    result = _minervini(df)
    if "error" in result:
        return f"Screen {code}: {result['error']}"

    cond_names = [
        "Price > SMA150 & SMA200",
        "SMA150 > SMA200",
        "SMA200 rising 1M",
        "SMA50 > SMA150 & SMA200",
        "Price > SMA50",
        "Price > 52wLow + 25%",
        "Price > 52wHigh - 25%",
    ]
    status = "PASS" if result["passed"] else "FAIL"
    lines  = [
        f"[{code}] {result['score']} {status}",
        f"  Price : {result['price']:,.0f}  "
        f"SMA50:{result['sma50']:,.0f}  SMA150:{result['sma150']:,.0f}  "
        f"SMA200:{result['sma200']:,.0f}",
        f"  52w   : High {result['high52']:,.0f}  Low {result['low52']:,.0f}  "
        f"({result['days']} days)",
        "",
    ]
    for ok, name in zip(result["conditions"], cond_names):
        lines.append(f"  {'✓' if ok else '✗'} {name}")
    return "\n".join(lines)


@mcp.tool()
def screen_all(top_n: int = 20) -> str:
    """
    Screen major stocks (20 default). Example: screen_all(20)
    """
    _init_db()
    codes   = MAJOR_STOCKS[:top_n]
    results = []
    for code in codes:
        try:
            bars = _fetch_daily(code)
            if bars:
                _save_weekly(code, _daily_to_weekly(bars))
                r = _minervini(_daily_to_df(bars))
                if "error" not in r:
                    results.append((code, r))
            time.sleep(REQUEST_SLEEP_SEC)
        except Exception:
            pass

    results.sort(key=lambda x: -int(x[1]["score"].split("/")[0]))
    passed = sum(1 for _, r in results if r["passed"])
    lines  = [f"Screened {len(results)} stocks  |  PASS: {passed}\n",
              f"  {'Code':<6}  {'Price':>8}  {'Score'}  {'High52':>8}  {'高値比':>6}",
              f"  {'-'*45}"]
    for code, r in results:
        mk     = ">>" if r["passed"] else "  "
        pct    = f"{r['price']/r['high52']*100:.1f}%" if r["high52"] else "  N/A"
        lines.append(f"{mk} {code:<6}  {r['price']:>8,.0f}  {r['score']}  "
                     f"{r['high52']:>8,.0f}  {pct:>6}")
    return "\n".join(lines)


@mcp.tool()
def get_weekly_csv(code: str) -> str:
    """Get weekly OHLCV CSV preview. Example: get_weekly_csv("6758")"""
    csv_path = CSV_DIR / f"{code}_weekly.csv"
    if not csv_path.exists():
        return f"No CSV for {code}. Run fetch_stock first."
    lines   = csv_path.read_text(encoding="utf-8").strip().split("\n")
    preview = "\n".join(lines[:6])
    return f"CSV: {csv_path}\nRows: {len(lines)-1}\n\n{preview}\n..."


@mcp.tool()
def list_stocks() -> str:
    """List all stocks saved in the database."""
    _init_db()
    con  = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT code, close, date FROM weekly_prices "
        "WHERE date=(SELECT MAX(date) FROM weekly_prices w2 WHERE w2.code=weekly_prices.code) "
        "ORDER BY code"
    ).fetchall()
    con.close()
    if not rows:
        return "No stocks saved. Use fetch_stock to get data."
    lines = [f"Saved {len(rows)} stocks:\n",
             f"  {'Code':<6}  {'Price':>8}  {'Date'}"]
    for code, close, date in rows:
        lines.append(f"  {code:<6}  {close:>8,.0f}  ({date[:10]})")
    return "\n".join(lines)

# ── 2. 全銘柄スクリーニング ──────────────────────────────────

@mcp.tool()
def get_equity_master(force_refresh: bool = False) -> str:
    """
    Download and cache JPX equity master (~4,400 stocks).
    force_refresh=True to bypass 7-day cache.
    """
    items        = fetch_equity_master(force=force_refresh)
    sector_count = {}
    for item in items:
        # V2: S17Nm、旧V1: Sector17CodeName
        s = item.get("S17Nm") or item.get("Sector17CodeName") or "Unknown"
        sector_count[s] = sector_count.get(s, 0) + 1
    top  = sorted(sector_count.items(), key=lambda x: -x[1])[:10]
    sl   = "\n".join(f"  {n}: {c}" for n, c in top)
    return (f"Equity master: {len(items)} stocks\nTop sectors:\n{sl}\n"
            f"Cache: {MASTER_CACHE}")


@mcp.tool()
def screen_full(
    resume:       bool = True,
    max_stocks:   int  = 0,
    sector_filter: str = "",
    exclude_etf:  bool = True,
) -> str:
    """
    Screen ALL JPX-listed stocks with Minervini + RS. Runs in background.
    resume      : continue from last interrupted run (default True).
    max_stocks  : limit for testing, 0 = all (~3800 excl ETF).
    sector_filter: e.g. "Electric Appliances", "Chemicals".
    exclude_etf : exclude ETF/REIT/investment trusts (default True).

    Use screen_full_status()  to monitor progress.
    Use screen_full_results() to query results.
    """
    global _job_state

    with _job_lock:
        if _job_state["running"]:
            done  = _job_state["done"]
            total = _job_state["total"]
            pct   = done / total * 100 if total else 0
            return (f"Already running: {done}/{total} ({pct:.1f}%)\n"
                    f"Use screen_full_status() to check progress.")

    items = fetch_equity_master()
    if exclude_etf:
        items = [i for i in items if not _is_etf(str(i.get("Code",""))[:4], i)]
    if sector_filter:
        items = [i for i in items
                 if sector_filter.lower() in
                    (i.get("S17Nm") or i.get("Sector17CodeName") or "").lower()]

    codes = [str(i["Code"])[:4] for i in items]
    total = len(codes) if max_stocks == 0 else min(max_stocks, len(codes))
    codes = codes[:total]

    if resume:
        prog = _load_progress()
        if prog.get("last_index", 0) >= total and total > 0:
            results    = _load_results()
            meta       = results.get("__meta__", {})
            pass_count = meta.get("passed", sum(
                1 for k, v in results.items()
                if k != "__meta__" and v.get("passed")))
            elapsed    = meta.get("elapsed_min", "?")
            started    = meta.get("started_at", "")[:16]
            return (f"前回完了済み: {total}銘柄  PASS:{pass_count}  "
                    f"所要:{elapsed}分  ({started})\n"
                    f"screen_full_results() で結果確認\n"
                    f"resume=False で再実行")

    started_at = datetime.now().isoformat()
    with _job_lock:
        _job_state.update({
            "running":     True,
            "done":        0,
            "total":       total,
            "passed":      0,
            "errors":      0,
            "started_at":  started_at,
            "finished_at": None,
            "elapsed_min": None,
            "status":      "running",
            "last_code":   "",
        })

    threading.Thread(
        target=_run_screen_full_bg,
        args=(codes, total, resume, started_at),
        daemon=True,
    ).start()

    etf_note = " ETF/REIT除外" if exclude_etf else ""
    return (f"スクリーニング開始: {total}銘柄{etf_note}\n"
            f"screen_full_status() で進捗確認\n"
            f"screen_full_results() で結果確認（完了後）")


@mcp.tool()
def screen_full_status() -> str:
    """Check progress of a running or completed screen_full job."""
    with _job_lock:
        state = dict(_job_state)

    if state["status"] in ("running", "complete"):
        done  = state["done"]
        total = state["total"]
        pct   = done / total * 100 if total else 0

        eta_str = ""
        if state["started_at"] and done > 0 and state["status"] == "running":
            elapsed   = (datetime.now() -
                         datetime.fromisoformat(state["started_at"])).total_seconds()
            remaining = (elapsed / done) * (total - done)
            eta_str   = (f"\n  経過: {elapsed/60:.1f}分  "
                         f"残り: {remaining/60:.1f}分")

        fin_str = ""
        if state["finished_at"]:
            fin_str = (f"\n  完了: {state['finished_at'][:16]}"
                       f"  所要: {state.get('elapsed_min','?')}分")

        return (f"Status  : {state['status']}\n"
                f"Progress: {done}/{total} ({pct:.1f}%){eta_str}\n"
                f"PASS    : {state['passed']}  Errors: {state['errors']}\n"
                f"Last    : {state['last_code']}{fin_str}")

    # Fallback to file
    prog    = _load_progress()
    results = _load_results()
    idx     = prog.get("last_index", 0)
    total   = prog.get("total", 0)
    if total == 0:
        return "No screen_full run found. Call screen_full() to start."

    pct         = idx / total * 100 if total else 0
    meta        = results.get("__meta__", {})
    pass_count  = meta.get("passed", sum(
        1 for k, v in results.items() if k != "__meta__" and v.get("passed")))
    elapsed_min = meta.get("elapsed_min")
    el_str      = f"\n  所要時間: {elapsed_min}分" if elapsed_min else ""
    status      = "complete" if idx >= total else "paused"

    return (f"Status  : {status} (file)\n"
            f"Progress: {idx}/{total} ({pct:.1f}%){el_str}\n"
            f"PASS    : {pass_count}  Results: {RESULTS_FILE}")


@mcp.tool()
def screen_full_results(
    min_score:   int  = 6,
    top_n:       int  = 50,
    near_high:   bool = False,
    exclude_etf: bool = True,
    sort_by:     str  = "score",
) -> str:
    """
    Query results from the last screen_full run.
    min_score  : minimum Minervini score (default 6).
    top_n      : rows to return (default 50).
    near_high  : True = only stocks within 5% of 52w high (高値更新圏).
    exclude_etf: exclude ETF/REIT (default True).
    sort_by    : "score" | "rs26w" | "price" | "high_pct"
    """
    results = _load_results()
    if not results:
        return "No results. Run screen_full() first."

    meta     = results.get("__meta__", {})
    meta_str = ""
    if meta:
        meta_str = (f"[前回実行: {meta.get('started_at','')[:16]}  "
                    f"所要: {meta.get('elapsed_min','?')}分  "
                    f"対象: {meta.get('total','?')}銘柄  "
                    f"PASS: {meta.get('passed','?')}]\n\n")

    filtered = []
    for k, v in results.items():
        if k == "__meta__" or v.get("error"):
            continue
        score = int(v.get("score", "0/7").split("/")[0])
        if score < min_score:
            continue
        if exclude_etf and _is_etf(v.get("code", "")):
            continue
        if near_high:
            price  = v.get("price", 0)
            high52 = v.get("high52", 0)
            if high52 <= 0 or price < high52 * 0.95:
                continue
        filtered.append((score, v))

    # Sort
    if sort_by == "rs26w":
        filtered.sort(key=lambda x: -(x[1].get("rs26w") or 0))
    elif sort_by == "price":
        filtered.sort(key=lambda x: -x[1].get("price", 0))
    elif sort_by == "high_pct":
        def _hp(v):
            p, h = v.get("price", 0), v.get("high52", 0)
            return -(p / h) if h else 0
        filtered.sort(key=lambda x: _hp(x[1]))
    else:
        filtered.sort(key=lambda x: -x[0])

    if not filtered:
        label = " (near 52w high)" if near_high else ""
        return f"No stocks with score >= {min_score}/7{label}."

    header = (f"  {'Code':<6}  {'Name':<22}  {'Sc':<4}  "
              f"{'Price':>9}  {'52wH':>9}  {'高値%':>6}  "
              f"{'RS6w':>6}  {'RS26w':>6}\n"
              f"  {'-'*80}\n")
    rows = []
    for _, r in filtered[:top_n]:
        price   = r.get("price", 0)
        high52  = r.get("high52", 0)
        hp      = f"{price/high52*100:.1f}%" if high52 else "  N/A"
        rs6     = f"{r['rs6w']:.2f}"  if r.get("rs6w")  else "  N/A"
        rs26    = f"{r['rs26w']:.2f}" if r.get("rs26w") else "  N/A"
        rows.append(
            f"  {r['code']:<6}  {r.get('name','')[:22]:<22}  {r['score']:<4}  "
            f"¥{price:>8,.0f}  ¥{high52:>8,.0f}  {hp:>6}  {rs6:>6}  {rs26:>6}"
        )

    label    = " 高値更新圏" if near_high else ""
    etf_note = " ETF除外" if exclude_etf else ""
    return (f"{meta_str}"
            f"≥{min_score}/7{label}{etf_note}  sort:{sort_by}  "
            f"({min(top_n, len(filtered))}/{len(filtered)}件)\n\n"
            f"{header}" + "\n".join(rows))

# ── 3. 業績データ ────────────────────────────────────────────

@mcp.tool()
def get_fins(code: str) -> str:
    """
    Fetch financial summary for a stock (sales / op-profit / net-profit / EPS).
    Example: get_fins("6758")
    """
    fins = _fetch_fins(code)
    if not fins:
        return f"No financial data for {code}."

    def fmt_jpy(v):
        if v is None: return "N/A"
        if v >= 1_000_000_000_000: return f"¥{v/1_000_000_000_000:.2f}兆"
        if v >= 100_000_000:       return f"¥{v/100_000_000:.1f}億"
        if v >= 1_000_000:         return f"¥{v/1_000_000:.1f}百万"
        return f"¥{v:,.0f}"

    def fmt(v):
        if v is None: return "N/A"
        if isinstance(v, float): return f"{v:.2f}"
        return str(v)

    name = _lookup_name(code)
    eq_ratio = fins.get("equity_ratio")
    eq_str   = f"{eq_ratio*100:.1f}%" if eq_ratio else "N/A"
    return (
        f"[{code}] {name}  業績 ({fins.get('fiscal_year','')} {fins.get('period','')})\n"
        f"  開示日    : {fins.get('disclosed_date','N/A')}\n"
        f"  売上高    : {fmt_jpy(fins.get('sales'))}\n"
        f"  営業利益  : {fmt_jpy(fins.get('op_profit'))}\n"
        f"  経常利益  : {fmt_jpy(fins.get('ord_profit'))}\n"
        f"  純利益    : {fmt_jpy(fins.get('net_profit'))}\n"
        f"  EPS       : {fmt(fins.get('eps'))}\n"
        f"  BPS       : {fmt(fins.get('bps'))}\n"
        f"  配当(年)  : {fmt(fins.get('div_annual'))}\n"
        f"  純資産    : {fmt_jpy(fins.get('equity'))}\n"
        f"  総資産    : {fmt_jpy(fins.get('total_assets'))}\n"
        f"  自己資本比: {eq_str}\n"
        f"  ── 予想 ──\n"
        f"  予想売上  : {fmt_jpy(fins.get('forecast_sales'))}\n"
        f"  予想純利益: {fmt_jpy(fins.get('forecast_profit'))}\n"
        f"  予想EPS   : {fmt(fins.get('forecast_eps'))}"
    )

@mcp.tool()
def debug_fins_raw(code: str) -> str:
    """
    Debug tool: show raw API response from /v2/fins/summary.
    Use code="master" to inspect equity master cache.
    Example: debug_fins_raw("6758"), debug_fins_raw("master")
    """
    # equity masterキャッシュの確認
    if code == "master":
        if not MASTER_CACHE.exists():
            return "Master cache not found."
        cached = json.loads(MASTER_CACHE.read_text(encoding="utf-8"))
        items  = cached.get("items", [])
        if not items:
            return "Master cache empty."
        sample = items[:3]
        return (f"Total: {len(items)} stocks\n"
                f"Keys : {list(items[0].keys())}\n\n"
                f"Sample:\n{json.dumps(sample, ensure_ascii=False, indent=2)[:1000]}")

    code_5 = code + "0"
    url    = f"https://api.jquants.com/v2/fins/summary?code={code_5}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=30)
        raw  = resp.json()
        keys    = list(raw.keys())
        first   = None
        for k in keys:
            v = raw[k]
            if isinstance(v, list) and v:
                first = v[-1]
                break
        return (f"Status : {resp.status_code}\n"
                f"Keys   : {keys}\n"
                f"Latest : {json.dumps(first, ensure_ascii=False, indent=2)[:800]}")
    except Exception as e:
        return f"ERROR: {e}"

# ── 4. ポートフォリオ管理 ─────────────────────────────────────

def _load_portfolio() -> dict:
    if PORTFOLIO_FILE.exists():
        return json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    return {}

def _save_portfolio(p: dict):
    PORTFOLIO_FILE.write_text(
        json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8"
    )

@mcp.tool()
def portfolio_add(code: str, shares: float, cost: float) -> str:
    """
    Add or update a holding.
    code  : stock code (e.g. "6758")
    shares: number of shares held
    cost  : average purchase price per share (JPY)
    Example: portfolio_add("6758", 100, 3200)
    """
    p    = _load_portfolio()
    name = _lookup_name(code)
    # キャッシュになければAPI取得を試みる
    if not name:
        try:
            fetch_equity_master()
            name = _lookup_name(code)
        except Exception:
            pass
    p[code] = {
        "code":     code,
        "name":     name,
        "shares":   shares,
        "cost":     cost,
        "added_at": datetime.now().isoformat(),
    }
    _save_portfolio(p)
    return f"Portfolio updated: {code} {name}  {shares}株 @ ¥{cost:,.0f}"


@mcp.tool()
def portfolio_remove(code: str) -> str:
    """Remove a stock from portfolio. Example: portfolio_remove("6758")"""
    p = _load_portfolio()
    if code not in p:
        return f"{code} is not in portfolio."
    del p[code]
    _save_portfolio(p)
    return f"Removed {code} from portfolio."


@mcp.tool()
def portfolio_show() -> str:
    """
    Show portfolio with current prices and P&L.
    Fetches latest price from saved daily CSV (no API call).
    """
    p = _load_portfolio()
    if not p:
        return "Portfolio is empty. Use portfolio_add() to add holdings."

    total_cost  = 0.0
    total_value = 0.0
    lines = [f"  {'Code':<6}  {'Name':<20}  {'株数':>6}  "
             f"{'取得単価':>9}  {'現在値':>9}  {'損益':>10}  {'損益率':>7}",
             f"  {'-'*75}"]

    for code, h in p.items():
        shares = h["shares"]
        cost   = h["cost"]
        # Try to read latest price from daily CSV
        csv_path = CSV_DIR / f"{code}_daily.csv"
        current  = None
        if csv_path.exists():
            try:
                df      = pd.read_csv(csv_path)
                current = float(df["close"].iloc[-1])
            except Exception:
                pass

        if current is not None:
            pnl     = (current - cost) * shares
            pnl_pct = (current / cost - 1) * 100
            total_cost  += cost * shares
            total_value += current * shares
            sign = "+" if pnl >= 0 else ""
            lines.append(
                f"  {code:<6}  {h.get('name','')[:20]:<20}  {shares:>6,.0f}  "
                f"¥{cost:>8,.0f}  ¥{current:>8,.0f}  "
                f"{sign}¥{pnl:>8,.0f}  {sign}{pnl_pct:>5.1f}%"
            )
        else:
            lines.append(
                f"  {code:<6}  {h.get('name','')[:20]:<20}  {shares:>6,.0f}  "
                f"¥{cost:>8,.0f}  (価格未取得)"
            )

    if total_cost > 0:
        total_pnl     = total_value - total_cost
        total_pnl_pct = (total_value / total_cost - 1) * 100
        sign = "+" if total_pnl >= 0 else ""
        lines += [
            f"  {'-'*75}",
            f"  {'合計':<28}  評価額: ¥{total_value:>12,.0f}  "
            f"損益: {sign}¥{total_pnl:>10,.0f}  ({sign}{total_pnl_pct:.1f}%)"
        ]

    return "\n".join(lines)

# ── 5. ウォッチリスト管理 ─────────────────────────────────────

def _load_watchlist() -> dict:
    if WATCHLIST_FILE.exists():
        return json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    return {}

def _save_watchlist(w: dict):
    WATCHLIST_FILE.write_text(
        json.dumps(w, ensure_ascii=False, indent=2), encoding="utf-8"
    )

@mcp.tool()
def watchlist_add(code: str, memo: str = "") -> str:
    """
    Add a stock to watchlist with optional memo.
    Example: watchlist_add("6758", "高値ブレイクアウト待ち")
    """
    w    = _load_watchlist()
    name = _lookup_name(code)
    if not name:
        try:
            fetch_equity_master()
            name = _lookup_name(code)
        except Exception:
            pass
    w[code] = {
        "code":     code,
        "name":     name,
        "memo":     memo,
        "added_at": datetime.now().isoformat(),
    }
    _save_watchlist(w)
    return f"Watchlist追加: {code} {name}  memo: {memo}"


@mcp.tool()
def watchlist_remove(code: str) -> str:
    """Remove a stock from watchlist. Example: watchlist_remove("6758")"""
    w = _load_watchlist()
    if code not in w:
        return f"{code} is not in watchlist."
    del w[code]
    _save_watchlist(w)
    return f"Removed {code} from watchlist."


@mcp.tool()
def watchlist_show() -> str:
    """
    Show watchlist with current Minervini score and price.
    Reads from saved daily CSV (no API call).
    """
    w = _load_watchlist()
    if not w:
        return "Watchlist is empty. Use watchlist_add() to add stocks."

    lines = [f"  {'Code':<6}  {'Name':<22}  {'Score':<5}  "
             f"{'Price':>9}  {'52wH':>9}  {'高値%':>6}  Memo",
             f"  {'-'*75}"]

    for code, item in w.items():
        csv_path = CSV_DIR / f"{code}_daily.csv"
        score_str = "N/A"
        price_str = "N/A"
        high_str  = "N/A"
        hp_str    = "N/A"

        if csv_path.exists():
            try:
                df     = pd.read_csv(csv_path, parse_dates=["date"]).set_index("date")
                result = _minervini(df)
                if "error" not in result:
                    price  = result["price"]
                    high52 = result["high52"]
                    score_str = result["score"]
                    price_str = f"¥{price:>8,.0f}"
                    high_str  = f"¥{high52:>8,.0f}"
                    hp_str    = f"{price/high52*100:.1f}%" if high52 else "N/A"
            except Exception:
                pass

        lines.append(
            f"  {code:<6}  {item.get('name','')[:22]:<22}  {score_str:<5}  "
            f"{price_str:>9}  {high_str:>9}  {hp_str:>6}  {item.get('memo','')}"
        )

    return "\n".join(lines)


@mcp.tool()
def watchlist_screen() -> str:
    """
    Run Minervini screening on all watchlist stocks and update prices via API.
    Example: watchlist_screen()
    """
    w = _load_watchlist()
    if not w:
        return "Watchlist is empty."

    lines = [f"Watchlist screening ({len(w)} stocks)\n",
             f"  {'Code':<6}  {'Name':<22}  {'Score':<5}  "
             f"{'Price':>9}  {'52wH':>9}  {'高値%':>6}",
             f"  {'-'*65}"]

    for code in w:
        try:
            bars   = _fetch_daily(code)
            df     = _daily_to_df(bars)
            result = _minervini(df)
            if "error" not in result:
                price  = result["price"]
                high52 = result["high52"]
                hp     = f"{price/high52*100:.1f}%" if high52 else "N/A"
                status = "PASS" if result["passed"] else "----"
                lines.append(
                    f"  {code:<6}  {w[code].get('name','')[:22]:<22}  "
                    f"{result['score']:<5}  ¥{price:>8,.0f}  "
                    f"¥{high52:>8,.0f}  {hp:>6}  {status}"
                )
                # Save latest data
                _init_db()
                _save_weekly(code, _daily_to_weekly(bars))
                _daily_to_df(bars).reset_index().to_csv(
                    CSV_DIR / f"{code}_daily.csv", index=False
                )
            time.sleep(REQUEST_SLEEP_SEC)
        except Exception as e:
            lines.append(f"  {code:<6}  ERROR: {e}")

    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Chart generation (Plotly candlestick)
# ---------------------------------------------------------------------------

def _load_daily_csv(code: str) -> pd.DataFrame:
    """Load daily data: DB (historical) + CSV (latest), merged and deduplicated."""
    frames = []

    # 1. Load from DB (long history)
    db_df = _load_daily_db(code)
    if not db_df.empty:
        frames.append(db_df)

    # 2. Load from CSV (latest ~400 days)
    csv_path = CSV_DIR / f"{code}_daily.csv"
    if csv_path.exists():
        try:
            csv_df = pd.read_csv(csv_path, parse_dates=["date"])
            csv_df = csv_df.sort_values("date").set_index("date")
            frames.append(csv_df)
        except Exception:
            pass

    if not frames:
        return pd.DataFrame()

    # Merge: concat and deduplicate (keep latest data for overlapping dates)
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()
    return df


@mcp.tool()
def generate_chart(code: str, show_patterns: bool = True) -> str:
    """ローソク足チャートを生成してブラウザで表示する。

    SMA50/150/200、出来高、52週高値/安値ラインを含む本格的なチャート。
    show_patterns=True の場合、検出されたパターンもチャート上に表示。

    Args:
        code: 4桁銘柄コード
        show_patterns: パターン検出結果をチャートに重ねるか
    """
    # Load data (CSV first, fallback to API)
    df = _load_daily_csv(code)
    if df.empty:
        try:
            bars = _fetch_daily(code)
            if not bars:
                return f"ERROR: No price data for {code}"
            df = _daily_to_df(bars)
            # Save CSV for future use
            df.reset_index().to_csv(CSV_DIR / f"{code}_daily.csv", index=False)
        except Exception as e:
            return f"ERROR fetching data: {e}"

    if len(df) < 50:
        return f"ERROR: Only {len(df)} days of data (need >= 50)"

    c = df["close"].values.astype(float)
    sma50  = pd.Series(c).rolling(50).mean()
    sma150 = pd.Series(c).rolling(150).mean()
    sma200 = pd.Series(c).rolling(200).mean()
    high52 = pd.Series(c).rolling(min(252, len(c))).max()
    low52  = pd.Series(c).rolling(min(252, len(c))).min()

    dates = df.index

    # Create subplots: candlestick + volume
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.75, 0.25],
    )

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=dates, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name="OHLC",
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
    ), row=1, col=1)

    # SMAs
    for sma, name, color in [
        (sma50,  "SMA50",  "#2196F3"),
        (sma150, "SMA150", "#FF9800"),
        (sma200, "SMA200", "#9C27B0"),
    ]:
        fig.add_trace(go.Scatter(
            x=dates, y=sma.values, name=name,
            line=dict(color=color, width=1.2),
        ), row=1, col=1)

    # 52-week high/low
    fig.add_trace(go.Scatter(
        x=dates, y=high52.values, name="52W High",
        line=dict(color="rgba(255,0,0,0.3)", width=1, dash="dot"),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=dates, y=low52.values, name="52W Low",
        line=dict(color="rgba(0,128,0,0.3)", width=1, dash="dot"),
    ), row=1, col=1)

    # Volume bars
    colors = ["#26a69a" if df["close"].iloc[i] >= df["open"].iloc[i]
              else "#ef5350" for i in range(len(df))]
    fig.add_trace(go.Bar(
        x=dates, y=df["volume"], name="Volume",
        marker_color=colors, opacity=0.7,
    ), row=2, col=1)

    # Pattern annotations
    if show_patterns:
        try:
            patterns = _detect_all_patterns(df)
            for p_name, p_data in patterns.items():
                if p_data.get("detected"):
                    details = p_data.get("details", {})
                    pivot = details.get("pivot_price") or details.get("resistance")
                    if pivot:
                        fig.add_hline(
                            y=pivot, line_dash="dash", line_color="gold",
                            annotation_text=f"{p_name} pivot: {pivot:.0f}",
                            row=1, col=1,
                        )
        except Exception:
            pass

    fig.update_layout(
        title=f"{code} Daily Chart",
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        height=700, width=1100,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=50, r=30, t=60, b=30),
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)

    # Save & open
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    html_path = CHART_DIR / f"{code}_chart.html"
    fig.write_html(str(html_path), include_plotlyjs=True)
    webbrowser.open(html_path.as_uri())

    return f"OK: Chart saved to {html_path} and opened in browser"


# ---------------------------------------------------------------------------
# Chart pattern detection
# ---------------------------------------------------------------------------

def _find_swing_highs(closes: list, window: int = 10) -> list:
    """Find swing high indices (local maxima)."""
    highs = []
    for i in range(window, len(closes) - window):
        if closes[i] == max(closes[i - window: i + window + 1]):
            highs.append(i)
    return highs


def _find_swing_lows(closes: list, window: int = 10) -> list:
    """Find swing low indices (local minima)."""
    lows = []
    for i in range(window, len(closes) - window):
        if closes[i] == min(closes[i - window: i + window + 1]):
            lows.append(i)
    return lows


def _detect_cup_with_handle(df: pd.DataFrame) -> dict:
    """
    Cup with Handle detection.
    - Cup: U-shaped base, 15-65 days, depth 12-35%
    - Handle: shallow pullback from right rim, 5-25 days, < 1/2 cup depth
    - Pivot: handle high + small buffer
    """
    closes = df["close"].values.astype(float).tolist()
    n = len(closes)
    if n < 60:
        return {"detected": False, "confidence": 0, "details": {}}

    # Search for cup patterns in recent data (last 120 days)
    search_start = max(0, n - 120)
    best = None

    swing_highs = _find_swing_highs(closes[search_start:], window=8)
    swing_highs = [i + search_start for i in swing_highs]

    for left_rim_idx in swing_highs:
        left_rim_price = closes[left_rim_idx]

        # Look for cup bottom after left rim
        cup_end_range = min(left_rim_idx + 66, n)
        if cup_end_range - left_rim_idx < 15:
            continue

        segment = closes[left_rim_idx:cup_end_range]
        bottom_offset = segment.index(min(segment))
        bottom_idx = left_rim_idx + bottom_offset
        bottom_price = closes[bottom_idx]

        cup_depth_pct = (left_rim_price - bottom_price) / left_rim_price
        if not (0.12 <= cup_depth_pct <= 0.35):
            continue

        # Check U-shape: bottom should be roughly in middle third
        cup_len = cup_end_range - left_rim_idx
        if not (cup_len * 0.25 < bottom_offset < cup_len * 0.75):
            continue

        # Right rim: find recovery back toward left rim price
        right_rim_idx = None
        for j in range(bottom_idx + 5, min(bottom_idx + 50, n)):
            if closes[j] >= left_rim_price * 0.95:
                right_rim_idx = j
                break
        if right_rim_idx is None:
            continue

        # Handle: shallow pullback after right rim
        handle_end = min(right_rim_idx + 26, n)
        if handle_end - right_rim_idx < 5:
            continue

        handle_seg = closes[right_rim_idx:handle_end]
        handle_low = min(handle_seg)
        handle_depth_pct = (closes[right_rim_idx] - handle_low) / closes[right_rim_idx]

        # Handle should be shallow (less than half of cup depth)
        if handle_depth_pct > cup_depth_pct * 0.5:
            continue
        if handle_depth_pct < 0.02:
            continue

        # Pivot price: right rim high + 0.5%
        pivot_price = max(handle_seg) * 1.005

        confidence = min(1.0, 0.5
                         + (0.2 if 0.15 <= cup_depth_pct <= 0.30 else 0)
                         + (0.15 if handle_depth_pct <= cup_depth_pct * 0.33 else 0)
                         + (0.15 if cup_len >= 25 else 0))

        if best is None or confidence > best["confidence"]:
            reason = (
                f"左リム{left_rim_price:.0f}円→底{bottom_price:.0f}円"
                f"(深さ{cup_depth_pct*100:.1f}%)→右リム回復。"
                f"ハンドル調整{handle_depth_pct*100:.1f}%。"
                f"ピボット{pivot_price:.0f}円。"
                f"カップ期間{right_rim_idx - left_rim_idx}日"
            )
            best = {
                "detected": True,
                "confidence": round(confidence, 2),
                "reason": reason,
                "details": {
                    "left_rim_idx": left_rim_idx,
                    "left_rim_price": round(left_rim_price, 1),
                    "bottom_idx": bottom_idx,
                    "bottom_price": round(bottom_price, 1),
                    "right_rim_idx": right_rim_idx,
                    "cup_depth_pct": round(cup_depth_pct * 100, 1),
                    "handle_depth_pct": round(handle_depth_pct * 100, 1),
                    "cup_length_days": right_rim_idx - left_rim_idx,
                    "pivot_price": round(pivot_price, 1),
                },
            }

    return best or {"detected": False, "confidence": 0, "details": {}}


def _detect_vcp(df: pd.DataFrame) -> dict:
    """
    VCP (Volatility Contraction Pattern) detection.
    - At least 2 contractions where range shrinks 20%+ each time
    - Volume declining during contractions
    """
    closes = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    volumes = df["volume"].values.astype(float)
    n = len(closes)
    if n < 40:
        return {"detected": False, "confidence": 0, "details": {}}

    # Analyze last 80 days
    lookback = min(80, n)
    start = n - lookback

    # Find contractions: split into segments by swing highs
    seg_ranges = []
    seg_volumes = []
    seg_size = lookback // 4  # ~20 day segments

    for i in range(4):
        s = start + i * seg_size
        e = min(s + seg_size, n)
        if e <= s:
            break
        seg_high = max(highs[s:e])
        seg_low = min(lows[s:e])
        seg_range_pct = (seg_high - seg_low) / seg_high if seg_high > 0 else 0
        seg_ranges.append(seg_range_pct)
        seg_volumes.append(sum(volumes[s:e]) / (e - s))

    if len(seg_ranges) < 3:
        return {"detected": False, "confidence": 0, "details": {}}

    # Count contractions (range shrinking)
    contractions = 0
    vol_declining = 0
    for i in range(1, len(seg_ranges)):
        if seg_ranges[i] < seg_ranges[i - 1] * 0.85:
            contractions += 1
        if seg_volumes[i] < seg_volumes[i - 1]:
            vol_declining += 1

    detected = contractions >= 2
    if not detected:
        return {"detected": False, "confidence": 0, "details": {}}

    # Resistance line: recent swing high
    recent_high = max(highs[n - 20:])
    confidence = min(1.0, 0.4
                     + contractions * 0.15
                     + vol_declining * 0.1)

    ranges_str = "→".join(f"{r*100:.1f}%" for r in seg_ranges)
    reason = (
        f"収縮{contractions}回検出。レンジ: {ranges_str}。"
        f"出来高減少{vol_declining}回。"
        f"レジスタンス{recent_high:.0f}円"
    )
    return {
        "detected": True,
        "confidence": round(confidence, 2),
        "reason": reason,
        "details": {
            "contractions": contractions,
            "vol_declining_segments": vol_declining,
            "ranges_pct": [round(r * 100, 1) for r in seg_ranges],
            "resistance": round(float(recent_high), 1),
            "current_range_pct": round(seg_ranges[-1] * 100, 1),
        },
    }


def _detect_flat_base(df: pd.DataFrame) -> dict:
    """
    Flat Base detection.
    - Range within 15% over 20-65 days
    - Volume below average
    """
    closes = df["close"].values.astype(float)
    volumes = df["volume"].values.astype(float)
    n = len(closes)
    if n < 20:
        return {"detected": False, "confidence": 0, "details": {}}

    avg_vol = volumes[-min(100, n):].mean()
    best = None

    for length in range(20, min(66, n)):
        seg = closes[-length:]
        seg_high = max(seg)
        seg_low = min(seg)
        range_pct = (seg_high - seg_low) / seg_high if seg_high > 0 else 0

        if range_pct > 0.15:
            continue

        seg_vol = volumes[-length:]
        vol_ratio = seg_vol.mean() / avg_vol if avg_vol > 0 else 1.0

        confidence = min(1.0, 0.5
                         + (0.2 if range_pct <= 0.10 else 0)
                         + (0.15 if vol_ratio < 0.8 else 0)
                         + (0.15 if length >= 30 else 0))

        if best is None or confidence > best["confidence"]:
            reason = (
                f"直近{length}日間のレンジ{range_pct*100:.1f}%"
                f"(高値{seg_high:.0f}円-安値{seg_low:.0f}円)。"
                f"出来高比{vol_ratio:.2f}倍。"
                f"レジスタンス{seg_high:.0f}円"
            )
            best = {
                "detected": True,
                "confidence": round(confidence, 2),
                "reason": reason,
                "details": {
                    "length_days": length,
                    "range_pct": round(range_pct * 100, 1),
                    "high": round(float(seg_high), 1),
                    "low": round(float(seg_low), 1),
                    "vol_ratio": round(vol_ratio, 2),
                    "resistance": round(float(seg_high), 1),
                },
            }

    return best or {"detected": False, "confidence": 0, "details": {}}


def _detect_all_patterns(df: pd.DataFrame) -> dict:
    """Run all pattern detectors on a DataFrame."""
    return {
        "cup_with_handle": _detect_cup_with_handle(df),
        "vcp": _detect_vcp(df),
        "flat_base": _detect_flat_base(df),
    }


@mcp.tool()
def detect_patterns(code: str) -> str:
    """銘柄のチャートパターンを検出する。

    Cup with Handle / VCP / Flat Base を判定。
    既存CSVデータを使用（APIコストなし）。CSVがなければAPIから取得。

    Args:
        code: 4桁銘柄コード
    """
    df = _load_daily_csv(code)
    if df.empty:
        try:
            bars = _fetch_daily(code)
            if not bars:
                return json.dumps({"error": f"No data for {code}"}, ensure_ascii=False)
            df = _daily_to_df(bars)
            df.reset_index().to_csv(CSV_DIR / f"{code}_daily.csv", index=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    results = _detect_all_patterns(df)
    results["code"] = code
    results["data_days"] = len(df)

    # Summary line
    detected = [k for k, v in results.items()
                if isinstance(v, dict) and v.get("detected")]
    results["summary"] = (
        f"{code}: {', '.join(detected)} detected" if detected
        else f"{code}: No pattern detected"
    )

    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool()
def screen_patterns(min_score: int = 6) -> str:
    """スクリーニングPASS銘柄のチャートパターンを一括検出する。

    screen_full の結果からスコアが min_score 以上の銘柄を対象に
    Cup with Handle / VCP / Flat Base を検出。APIコストなし（CSV使用）。

    Args:
        min_score: 最低スコア（デフォルト6）
    """
    if not RESULTS_FILE.exists():
        return "ERROR: screen_full results not found. Run screen_full first."

    data = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    # Build lookup: code -> item
    items = data.values() if isinstance(data, dict) else data
    lookup = {}
    for item in items:
        if isinstance(item, dict) and item.get("code"):
            lookup[item["code"]] = item

    candidates = []
    for code, item in lookup.items():
        score_str = item.get("score", "0/7")
        score = int(score_str.split("/")[0])
        if score >= min_score:
            candidates.append(code)

    if not candidates:
        return f"No stocks with score >= {min_score}"

    all_results = []
    for code in candidates:
        df = _load_daily_csv(code)
        if df.empty:
            all_results.append({"code": code, "error": "No CSV data"})
            continue
        patterns = _detect_all_patterns(df)
        detected = [k for k, v in patterns.items() if v.get("detected")]
        item = lookup.get(code, {})
        all_results.append({
            "code": code,
            "name": item.get("name", ""),
            "score": item.get("score", ""),
            "patterns": detected,
            "details": {k: v for k, v in patterns.items() if v.get("detected")},
        })

    # Separate: with patterns vs without
    with_patterns = [r for r in all_results if r.get("patterns")]
    without = [r for r in all_results if not r.get("patterns") and "error" not in r]

    # Save results
    output = {
        "__meta__": {
            "generated_at": datetime.now().isoformat(),
            "total_screened": len(candidates),
            "patterns_found": len(with_patterns),
            "min_score": min_score,
        },
        "with_patterns": with_patterns,
        "no_patterns": [{"code": r["code"], "name": r.get("name", "")}
                        for r in without],
    }

    result_path = BASE_DIR / "data" / "pattern_results.json"
    result_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Summary
    lines = [f"Pattern screening: {len(candidates)} stocks (score >= {min_score})"]
    lines.append(f"Patterns found: {len(with_patterns)} stocks\n")
    for r in with_patterns:
        patterns_str = ", ".join(r["patterns"])
        lines.append(f"  {r['code']}  {r.get('name',''):<10}  "
                      f"[{r.get('score','')}]  {patterns_str}")

    lines.append(f"\nResults saved to {result_path}")
    return "\n".join(lines)


def _export_one(code: str, df: pd.DataFrame, max_days: int,
                chart_data: dict, pattern_data: dict,
                timeline_data: dict = None):
    """Export chart + pattern data for a single stock."""
    df_clean = df.dropna(subset=["open", "high", "low", "close"]).tail(max_days)
    records = []
    for date, row in df_clean.iterrows():
        records.append({
            "time": date.strftime("%Y-%m-%d"),
            "open": round(float(row["open"]), 1),
            "high": round(float(row["high"]), 1),
            "low": round(float(row["low"]), 1),
            "close": round(float(row["close"]), 1),
            "volume": int(row["volume"]) if pd.notna(row["volume"]) else 0,
        })
    chart_data[code] = records

    patterns = _detect_all_patterns(df)
    detected = [k for k, v in patterns.items() if v.get("detected")]
    if detected:
        pattern_data[code] = {
            "patterns": detected,
            "details": {k: v for k, v in patterns.items() if v.get("detected")},
        }

    # Timeline: YTD high date, 52-week high date
    if timeline_data is not None:
        closes = df["close"].dropna()
        tl = {}
        # YTD high date
        try:
            ytd_start = f"{datetime.now().year}-01-01"
            ytd_df = closes[closes.index >= ytd_start]
            if not ytd_df.empty:
                ytd_high_date = ytd_df.idxmax()
                tl["ytd_high_date"] = ytd_high_date.strftime("%Y-%m-%d")
                tl["ytd_high_price"] = round(float(ytd_df.max()), 1)
        except Exception:
            pass
        # 52-week high date
        try:
            w52 = closes.tail(252)
            if not w52.empty:
                high52_date = w52.idxmax()
                tl["high52_date"] = high52_date.strftime("%Y-%m-%d")
                tl["high52_price"] = round(float(w52.max()), 1)
        except Exception:
            pass
        if tl:
            timeline_data[code] = tl


def _ensure_csv(code: str) -> pd.DataFrame:
    """Load data or fetch from API. Saves to both CSV and DB."""
    df = _load_daily_csv(code)
    if not df.empty:
        return df
    try:
        bars = _fetch_daily(code)
        if not bars:
            return pd.DataFrame()
        df = _daily_to_df(bars)
        CSV_DIR.mkdir(parents=True, exist_ok=True)
        df.reset_index().to_csv(CSV_DIR / f"{code}_daily.csv", index=False)
        _save_daily_db(code, df)  # Persist to DB for long-term storage
        time.sleep(REQUEST_SLEEP_SEC)
        return df
    except Exception:
        return pd.DataFrame()


@mcp.tool()
def export_chart_data(extra_codes: str = "", max_days: int = 200,
                      ytd_near_pct: float = 0.98) -> str:
    """サイト用チャート・パターンデータをエクスポートする。

    対象銘柄（自動選定）:
    1. 監視銘柄リスト（watchlist.json）の全銘柄 → 必ず含む
    2. ポートフォリオ（portfolio.json）の全銘柄 → 必ず含む
    3. 年初来高値更新圏（price >= ytd_high * ytd_near_pct）のPASS銘柄

    Args:
        extra_codes: カンマ区切りで追加銘柄コード（例: "7203,6758"）
        max_days: チャート日数（デフォルト200）
        ytd_near_pct: 年初来高値の何%以内を対象にするか（デフォルト0.98）
    """
    # Try invest-data (site version) first, fallback to local
    data = None
    _INVEST_DATA_URL = (
        "https://raw.githubusercontent.com/"
        "yangpinggaoye15-dotcom/invest-data/main/screen_full_results.json"
    )
    try:
        resp = requests.get(_INVEST_DATA_URL, timeout=15)
        if resp.ok:
            data = resp.json()
    except Exception:
        pass
    if data is None:
        if not RESULTS_FILE.exists():
            return "ERROR: screen_full results not found."
        data = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))

    items_dict = data if isinstance(data, dict) else {}
    if isinstance(data, list):
        items_dict = {i.get("code", ""): i for i in data if isinstance(i, dict)}

    # 1. Watchlist codes (always included)
    watchlist = _load_watchlist()
    wl_codes = set(watchlist.keys())

    # 2. Portfolio codes (always included)
    portfolio = _load_portfolio()
    pf_codes = set(portfolio.keys())

    # 3. YTD high stocks (PASS with price near ytd_high)
    ytd_codes = set()
    for code, item in items_dict.items():
        if code == "__meta__" or not isinstance(item, dict):
            continue
        if not item.get("passed"):
            continue
        ytd_high = item.get("ytd_high")
        price = item.get("price", 0)
        if ytd_high and price >= ytd_high * ytd_near_pct:
            ytd_codes.add(code)

    # 4. Extra codes from argument
    extra = set()
    if extra_codes:
        extra = {c.strip() for c in extra_codes.split(",") if c.strip()}

    target_codes = wl_codes | pf_codes | ytd_codes | extra
    if not target_codes:
        return "No target stocks found (no watchlist, portfolio, or YTD-high stocks)"

    chart_data = {}
    pattern_data = {}
    timeline_data = {}
    api_fetched = 0

    for code in sorted(target_codes):
        df = _load_daily_csv(code)
        if df.empty:
            df = _ensure_csv(code)
            if not df.empty:
                api_fetched += 1
        if df.empty:
            continue
        _export_one(code, df, max_days, chart_data, pattern_data,
                    timeline_data)

    # Save chart data
    chart_path = GITHUB_DIR / "chart_data.json"
    chart_path.write_text(
        json.dumps(chart_data, ensure_ascii=False), encoding="utf-8"
    )

    # Save pattern data
    pat_path = GITHUB_DIR / "pattern_data.json"
    pat_path.write_text(
        json.dumps(pattern_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Save timeline data (YTD high dates, 52w high dates)
    tl_path = GITHUB_DIR / "timeline_data.json"
    tl_path.write_text(
        json.dumps(timeline_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    sz = chart_path.stat().st_size // 1024
    return (
        f"OK: Exported {len(chart_data)} stocks (API fetched: {api_fetched})\n"
        f"  Watchlist: {len(wl_codes)}, Portfolio: {len(pf_codes)}, "
        f"YTD-high: {len(ytd_codes)}, Extra: {len(extra)}\n"
        f"  Chart data: {chart_path} ({sz} KB)\n"
        f"  Pattern data: {pat_path} (patterns: {len(pattern_data)})\n"
        f"  Timeline data: {tl_path} ({len(timeline_data)} stocks)\n"
        f"Push to invest-data repo to update the site."
    )


@mcp.tool()
def export_site_data() -> str:
    """watchlist.jsonとportfolio.jsonをGitHubリポジトリにコピーする。

    invest-dataにpushすればサイトで監視銘柄リスト・ポートフォリオが表示される。
    """
    copied = []
    for src_path, name in [
        (WATCHLIST_FILE, "watchlist.json"),
        (PORTFOLIO_FILE, "portfolio.json"),
    ]:
        dst = GITHUB_DIR / name
        if src_path.exists():
            content = src_path.read_text(encoding="utf-8")
            dst.write_text(content, encoding="utf-8")
            copied.append(f"  {name}: {dst}")
        else:
            # Write empty JSON
            dst.write_text("{}", encoding="utf-8")
            copied.append(f"  {name}: (empty) {dst}")

    return "OK: Copied to GITHUB_DIR\n" + "\n".join(copied)


KNOWLEDGE_DIR = GITHUB_DIR / "knowledge"


@mcp.tool()
def save_knowledge(code: str, text: str, category: str = "general") -> str:
    """銘柄のナレッジ（学習事項）をファイルに保存する。

    AIへの質問時に過去ナレッジとして参照される。

    Args:
        code: 4桁銘柄コード
        text: ナレッジ内容
        category: カテゴリ（general/news/plan/analysis/backtest）
    """
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    kl_path = KNOWLEDGE_DIR / f"{code}.json"
    entries = []
    if kl_path.exists():
        try:
            entries = json.loads(kl_path.read_text(encoding="utf-8"))
        except Exception:
            entries = []

    entries.insert(0, {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "category": category,
        "text": text[:1000],
    })
    # Keep max 20 per stock
    entries = entries[:20]

    kl_path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return f"OK: Knowledge saved for {code} ({len(entries)} entries)"


@mcp.tool()
def export_knowledge() -> str:
    """ナレッジデータをサイト用にエクスポートする。

    knowledge/*.json を1つの knowledge_data.json にまとめる。
    invest-dataにpushすればAI質問時に参照される。
    """
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    all_kl = {}
    for kl_file in KNOWLEDGE_DIR.glob("*.json"):
        code = kl_file.stem
        try:
            entries = json.loads(kl_file.read_text(encoding="utf-8"))
            if entries:
                all_kl[code] = entries
        except Exception:
            pass

    kl_path = GITHUB_DIR / "knowledge_data.json"
    kl_path.write_text(
        json.dumps(all_kl, ensure_ascii=False), encoding="utf-8"
    )
    return f"OK: Exported knowledge for {len(all_kl)} stocks to {kl_path}"


@mcp.tool()
def export_fins_data(extra_codes: str = "", ytd_near_pct: float = 0.98) -> str:
    """年初来高値圏+監視+ポートフォリオ銘柄の業績データをJSONエクスポートする。

    J-Quants APIから過去5年分の業績（通期+四半期+予想）を取得。
    invest-dataにpushすればサイトの業績ページに反映。

    Args:
        extra_codes: カンマ区切りで追加銘柄コード
        ytd_near_pct: 年初来高値の何%以内を対象にするか（デフォルト0.98）
    """
    # Try invest-data (site version) first, fallback to local
    data = None
    _INVEST_DATA_URL = (
        "https://raw.githubusercontent.com/"
        "yangpinggaoye15-dotcom/invest-data/main/screen_full_results.json"
    )
    try:
        resp = requests.get(_INVEST_DATA_URL, timeout=15)
        if resp.ok:
            data = resp.json()
    except Exception:
        pass
    if data is None:
        if not RESULTS_FILE.exists():
            return "ERROR: screen_full results not found."
        data = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))

    items_dict = data if isinstance(data, dict) else {}

    # Target stocks (same logic as export_chart_data)
    watchlist = _load_watchlist()
    portfolio = _load_portfolio()
    wl_codes = set(watchlist.keys())
    pf_codes = set(portfolio.keys())

    ytd_codes = set()
    for code, item in items_dict.items():
        if code == "__meta__" or not isinstance(item, dict):
            continue
        if not item.get("passed"):
            continue
        ytd_high = item.get("ytd_high")
        price = item.get("price", 0)
        if ytd_high and price >= ytd_high * ytd_near_pct:
            ytd_codes.add(code)

    extra = set()
    if extra_codes:
        extra = {c.strip() for c in extra_codes.split(",") if c.strip()}

    target_codes = wl_codes | pf_codes | ytd_codes | extra
    if not target_codes:
        return "No target stocks found"

    fins_data = {}
    fetched = 0
    errors = 0

    for code in sorted(target_codes):
        try:
            records = _fetch_fins_history(code)
            if records:
                fins_data[code] = records
                fetched += 1
            time.sleep(REQUEST_SLEEP_SEC)
        except Exception:
            errors += 1

    # Save
    fins_path = GITHUB_DIR / "fins_data.json"
    fins_path.write_text(
        json.dumps(fins_data, ensure_ascii=False), encoding="utf-8"
    )

    sz = fins_path.stat().st_size // 1024
    return (
        f"OK: Fetched financials for {fetched} stocks (errors: {errors})\n"
        f"  Target: WL={len(wl_codes)}, PF={len(pf_codes)}, "
        f"YTD={len(ytd_codes)}, Extra={len(extra)}\n"
        f"  Saved: {fins_path} ({sz} KB)"
    )


# ---------------------------------------------------------------------------
# General-purpose file & command tools
# ---------------------------------------------------------------------------

@mcp.tool()
def read_file(file_path: str) -> str:
    """指定パスのファイルを読み取る。

    Args:
        file_path: 絶対パスまたはリポジトリルートからの相対パス
    """
    target = Path(file_path)
    if not target.is_absolute():
        target = GITHUB_DIR / file_path
    if not target.exists():
        return f"ERROR: File not found: {target}"
    if not target.is_file():
        return f"ERROR: Not a file: {target}"
    try:
        return target.read_text(encoding="utf-8")
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def write_file(file_path: str, content: str) -> str:
    """指定パスにファイルを書き込む（上書き保存）。

    Args:
        file_path: 絶対パスまたはリポジトリルートからの相対パス
        content: ファイルの全内容
    """
    target = Path(file_path)
    if not target.is_absolute():
        target = GITHUB_DIR / file_path
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_text(content, encoding="utf-8")
        return f"OK: Saved {target} ({len(content)} chars)"
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def run_command(command: str, working_directory: str = "") -> str:
    """PowerShellコマンドを実行して結果を返す。

    Args:
        command: 実行するPowerShellコマンド
        working_directory: 作業ディレクトリ（空ならリポジトリルート）
    """
    cwd = working_directory if working_directory else str(GITHUB_DIR)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = result.stdout.strip()
        err = result.stderr.strip()
        parts = []
        if output:
            parts.append(output)
        if err:
            parts.append(f"[STDERR]\n{err}")
        if result.returncode != 0:
            parts.insert(0, f"[EXIT CODE: {result.returncode}]")
        return "\n".join(parts) if parts else "(no output)"
    except subprocess.TimeoutExpired:
        return "ERROR: Command timed out (300s limit)"
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()

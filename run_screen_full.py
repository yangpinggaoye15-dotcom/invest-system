import os, sys, time, json, logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timedelta
import requests
import pandas as pd

BASE_DIR = Path(os.environ.get("BASE_DIR", str(Path.home() / "invest-system")))
CSV_DIR = BASE_DIR / "csv_output"
CONFIG = Path.home() / ".jquants_config.json"
PROGRESS_FILE = BASE_DIR / "data" / "screen_full_progress.json"
RESULTS_FILE = BASE_DIR / "data" / "screen_full_results.json"
MASTER_CACHE = BASE_DIR / "data" / "equity_master_cache.json"
LOG_FILE = BASE_DIR / "data" / "screen_full.log"
MASTER_CACHE_TTL_DAYS = 1
BATCH_SIZE = 50
REQUEST_SLEEP_SEC = 0.1
MAX_RETRIES = 3
RETRY_SLEEP_SEC = 10.0
PARALLEL_WORKERS = 8
NIKKEI225_CODE = "1321"
ETF_CODE_PREFIXES = ("13","14","15","16","17","18","19")

(BASE_DIR / "data").mkdir(parents=True, exist_ok=True)
CSV_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

def _get_api_key():
    key = os.environ.get("JQUANTS_API_KEY", "")
    if key: return key
    if CONFIG.exists():
        return json.loads(CONFIG.read_text(encoding="utf-8")).get("jquants_api_key", "")
    raise RuntimeError("J-Quants API key not found.")

def _headers(): return {"x-api-key": _get_api_key()}

def _fetch_daily(code_4, days=400):
    code_5 = code_4 + "0"
    date_from = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    date_to = datetime.now().strftime("%Y%m%d")
    url = f"https://api.jquants.com/v2/equities/bars/daily?code={code_5}&from={date_from}&to={date_to}"
    resp = requests.get(url, headers=_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json().get("data", [])

def _daily_to_df(bars):
    df = pd.DataFrame(bars)
    df["date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("date").set_index("date")
    df["open"]   = df.get("AdjO", df["O"])
    df["high"]   = df.get("AdjH", df["H"])
    df["low"]    = df.get("AdjL", df["L"])
    df["close"]  = df.get("AdjC", df["C"])
    df["volume"] = df.get("AdjVo", df["Vo"])
    return df[["open","high","low","close","volume"]]

def _minervini(df):
    c = df["close"].values.astype(float)
    if len(c) < 52: return {"error": f"only {len(c)} days"}
    price = c[-1]
    sma50 = c[-min(50,len(c)):].mean()
    sma150 = c[-min(150,len(c)):].mean()
    sma200 = c[-min(200,len(c)):].mean()
    sma200_1m = c[-min(220,len(c)):-20].mean() if len(c)>=30 else sma200*0.999
    high52 = c[-min(252,len(c)):].max()
    low52 = c[-min(252,len(c)):].min()
    cond = [bool(price>sma150 and price>sma200), bool(sma150>sma200),
            bool(sma200>sma200_1m), bool(sma50>sma150 and sma50>sma200),
            bool(price>sma50), bool(price>low52*1.25), bool(price>high52*0.75)]
    n = sum(cond)
    return {"passed":n>=6,"score":f"{n}/7","conditions":cond,
            "price":round(float(price),1),"sma50":round(float(sma50),1),
            "sma150":round(float(sma150),1),"sma200":round(float(sma200),1),
            "high52":round(float(high52),1),"low52":round(float(low52),1)}

def _calc_rs(s, b):
    def pct(a,n): return (a[-1]/a[-n-1]-1.0) if len(a)>=n+1 else None
    def sdiv(a,b):
        if a is None or b is None or b==-1: return None
        return round(a/b,3)
    return {"rs6w":sdiv(pct(s,6),pct(b,6)),"rs13w":sdiv(pct(s,13),pct(b,13)),"rs26w":sdiv(pct(s,26),pct(b,26))}

def _is_etf(code_4, item=None):
    if str(code_4).startswith(ETF_CODE_PREFIXES): return True
    if item and any(t.lower() in str(item.get("TypeCode","")).lower() for t in {"ETF","REIT","ETN","InfFund","PRF"}): return True
    return False

def fetch_equity_master():
    if MASTER_CACHE.exists():
        cached = json.loads(MASTER_CACHE.read_text(encoding="utf-8"))
        if datetime.now()-datetime.fromisoformat(cached["fetched_at"])<timedelta(days=MASTER_CACHE_TTL_DAYS):
            log.info(f"Master cache: {cached['count']} stocks")
            return cached["items"]
    log.info("Fetching equity master...")
    resp = requests.get("https://api.jquants.com/v2/equities/master",headers=_headers(),timeout=30)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("info",data.get("data",[]))
    eq = [i for i in items if len(str(i.get("Code","")))==5 and str(i.get("Code",""))[-1]=="0"]
    MASTER_CACHE.write_text(json.dumps({"fetched_at":datetime.now().isoformat(),"count":len(eq),"items":eq},ensure_ascii=False,indent=2),encoding="utf-8")
    log.info(f"Master fetched: {len(eq)} stocks")
    return eq

def _lookup_name(code_4):
    if not MASTER_CACHE.exists(): return ""
    master = json.loads(MASTER_CACHE.read_text(encoding="utf-8"))
    code_5 = code_4+"0"
    for item in master.get("items",[]):
        if str(item.get("Code",""))==code_5:
            return item.get("CoNameEn") or item.get("CoName") or item.get("CompanyNameEnglish") or item.get("CompanyName","")
    return ""

def _load_progress():
    if PROGRESS_FILE.exists(): return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return {"last_index":0,"started_at":None,"total":0}

def _save_progress(index,total,started_at):
    PROGRESS_FILE.write_text(json.dumps({"last_index":index,"total":total,"started_at":started_at},ensure_ascii=False),encoding="utf-8")

def _load_results():
    if RESULTS_FILE.exists(): return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    return {}

def _save_results(results):
    RESULTS_FILE.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")

def _screen_one(code_4, bench_closes=None):
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(REQUEST_SLEEP_SEC)
            bars = _fetch_daily(code_4)
            if not bars or len(bars)<10: return {"code":code_4,"error":"insufficient data"}
            df = _daily_to_df(bars)
            result = _minervini(df)
            if "error" in result: return {"code":code_4,"error":result["error"]}
            rs = _calc_rs(df["close"].tolist(),bench_closes) if bench_closes else {}
            return {"code":code_4,"name":_lookup_name(code_4),"price":result["price"],
                    "passed":result["passed"],"score":result["score"],"high52":result["high52"],
                    "low52":result["low52"],"sma50":result["sma50"],"sma150":result["sma150"],
                    "sma200":result["sma200"],"conditions":result["conditions"],
                    "rs6w":rs.get("rs6w"),"rs13w":rs.get("rs13w"),"rs26w":rs.get("rs26w")}
        except Exception as e:
            err = str(e)
            if "429" in err or "rate" in err.lower():
                time.sleep(RETRY_SLEEP_SEC*(attempt+1))
            elif attempt==MAX_RETRIES-1: return {"code":code_4,"error":err}
            else: time.sleep(RETRY_SLEEP_SEC)
    return {"code":code_4,"error":"max retries exceeded"}

def run(resume=True, max_stocks=0, exclude_etf=True):
    log.info("="*60)
    log.info(f"screen_full start resume={resume} exclude_etf={exclude_etf}")
    items = fetch_equity_master()
    if exclude_etf: items = [i for i in items if not _is_etf(str(i.get("Code",""))[:4],i)]
    codes = [str(i["Code"])[:4] for i in items]
    total = len(codes) if max_stocks==0 else min(max_stocks,len(codes))
    codes = codes[:total]
    log.info(f"Target: {total} stocks")
    bench_closes = []
    try:
        bench_closes = _daily_to_df(_fetch_daily(NIKKEI225_CODE))["close"].tolist()
        log.info(f"Nikkei225: {len(bench_closes)} days")
    except Exception as e: log.warning(f"Nikkei225 failed: {e}")
    results = _load_results() if resume else {}
    start_idx = _load_progress().get("last_index",0) if resume else 0
    started_at = datetime.now().isoformat()
    errors = passed = batch_count = 0
    pending = [c for c in codes[start_idx:] if not (c in results and not results[c].get("error"))]
    log.info(f"Pending: {len(pending)} stocks Workers: {PARALLEL_WORKERS}")
    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
        future_to_code = {executor.submit(_screen_one,code,bench_closes):code for code in pending}
        for future in as_completed(future_to_code):
            code = future_to_code[future]
            try: res = future.result()
            except Exception as e: res = {"code":code,"error":str(e)}
            results[code]=res; batch_count+=1
            if res.get("error"): errors+=1
            elif res.get("passed"): passed+=1
            if batch_count%BATCH_SIZE==0:
                done=start_idx+batch_count; _save_progress(done,total,started_at); _save_results(results)
                log.info(f"Progress: {done}/{total} ({done/total*100:.1f}%) PASS:{passed} ERR:{errors}")
    finished_at = datetime.now().isoformat()
    elapsed_min = round((datetime.now()-datetime.fromisoformat(started_at)).total_seconds()/60,1)
    pass_count = sum(1 for k,v in results.items() if k!="__meta__" and v.get("passed"))
    results["__meta__"] = {"started_at":started_at,"finished_at":finished_at,"elapsed_min":elapsed_min,
                            "total":total,"passed":pass_count,"errors":errors,"mode":"fresh" if not resume else "resume"}
    _save_results(results)
    log.info("="*60)
    log.info(f"Done! {total} stocks PASS:{pass_count} ERR:{errors} elapsed:{elapsed_min}min")

def update():
    log.info("="*60)
    log.info("UPDATE MODE: daily delta update")
    items = fetch_equity_master()
    items = [i for i in items if not _is_etf(str(i.get("Code",""))[:4],i)]
    codes = [str(i["Code"])[:4] for i in items]
    total = len(codes)
    log.info(f"Target: {total} stocks")
    bench_closes = []
    try:
        bench_csv = CSV_DIR/f"{NIKKEI225_CODE}_daily.csv"
        new_bars = _fetch_daily(NIKKEI225_CODE,days=5)
        if new_bars and bench_csv.exists():
            existing = pd.read_csv(bench_csv,parse_dates=["date"]).set_index("date")
            new_df = _daily_to_df(new_bars)
            merged = pd.concat([existing,new_df])
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
            merged.reset_index().to_csv(bench_csv,index=False)
            bench_closes = merged["close"].tolist()
        elif new_bars: bench_closes = _daily_to_df(new_bars)["close"].tolist()
        log.info(f"Nikkei225: {len(bench_closes)} days")
    except Exception as e: log.warning(f"Nikkei225 update failed: {e}")
    results = _load_results()
    started_at = datetime.now().isoformat()
    errors = passed = batch_count = 0
    def _update_one(code_4):
        try:
            new_bars = _fetch_daily(code_4,days=5)
            if not new_bars: return None
            csv_path = CSV_DIR/f"{code_4}_daily.csv"
            if csv_path.exists():
                existing = pd.read_csv(csv_path,parse_dates=["date"]).set_index("date")
                new_df = _daily_to_df(new_bars)
                merged = pd.concat([existing,new_df])
                merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                merged.reset_index().to_csv(csv_path,index=False)
                df = merged
            else:
                full_bars = _fetch_daily(code_4,days=400)
                df = _daily_to_df(full_bars)
                df.reset_index().to_csv(csv_path,index=False)
            result = _minervini(df)
            if "error" in result: return {"code":code_4,"error":result["error"]}
            rs = _calc_rs(df["close"].tolist(),bench_closes) if bench_closes else {}
            return {"code":code_4,"name":_lookup_name(code_4),"price":result["price"],
                    "passed":result["passed"],"score":result["score"],"high52":result["high52"],
                    "low52":result["low52"],"sma50":result["sma50"],"sma150":result["sma150"],
                    "sma200":result["sma200"],"conditions":result["conditions"],
                    "rs6w":rs.get("rs6w"),"rs13w":rs.get("rs13w"),"rs26w":rs.get("rs26w")}
        except Exception as e: return {"code":code_4,"error":str(e)}
    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
        future_to_code = {executor.submit(_update_one,c):c for c in codes}
        for future in as_completed(future_to_code):
            code = future_to_code[future]
            try: res = future.result()
            except Exception as e: res = {"code":code,"error":str(e)}
            if res is None: continue
            results[code]=res; batch_count+=1
            if res.get("error"): errors+=1
            elif res.get("passed"): passed+=1
            if batch_count%BATCH_SIZE==0:
                _save_progress(batch_count,total,started_at); _save_results(results)
                log.info(f"Progress: {batch_count}/{total} ({batch_count/total*100:.1f}%) PASS:{passed} ERR:{errors}")
    finished_at = datetime.now().isoformat()
    elapsed_min = round((datetime.now()-datetime.fromisoformat(started_at)).total_seconds()/60,1)
    pass_count = sum(1 for k,v in results.items() if k!="__meta__" and v.get("passed"))
    results["__meta__"] = {"started_at":started_at,"finished_at":finished_at,"elapsed_min":elapsed_min,
                            "total":total,"passed":pass_count,"errors":errors,"mode":"update"}
    _save_results(results)
    log.info("="*60)
    log.info(f"Update done! {total} stocks PASS:{pass_count} ERR:{errors} elapsed:{elapsed_min}min")

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--test" in args:
        log.info("TEST MODE: first 20 stocks")
        run(resume=False, max_stocks=20)
    elif "--fresh" in args:
        log.info("FRESH MODE: all stocks from scratch")
        run(resume=False)
    elif "--update" in args:
        log.info("UPDATE MODE: daily delta")
        update()
    else:
        log.info("RESUME MODE: continuing from last run")
        run(resume=True)


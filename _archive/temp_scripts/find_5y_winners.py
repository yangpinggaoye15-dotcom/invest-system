#!/usr/bin/env python3
"""
5年で3倍以上になった銘柄を全件抽出するスクリプト
J-Quants V2 API を直接叩き、並列で取得する

Usage:
  python find_5y_winners.py              # 5年3倍以上
  python find_5y_winners.py --years 3   # 3年2倍以上
  python find_5y_winners.py --min 300   # 4倍以上
"""

import sys, io, os, json, time, csv, argparse
import requests
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_DIR = Path(r'C:\Users\yohei\Documents\invest-system-github')
DATA_DIR = BASE_DIR / 'data'
CSV_DIR  = BASE_DIR / 'csv_output'
OUT_DIR  = BASE_DIR / 'reports'

ENV_FILES = [BASE_DIR / '.env', BASE_DIR / '.env.monitor']

# デフォルト設定
YEARS     = 5
MIN_GAIN  = 200.0   # 200% = 3倍
WORKERS   = 5
SLEEP_429 = 8

def load_env() -> dict:
    env = {}
    for ef in ENV_FILES:
        if ef.exists():
            for line in ef.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env

def get_api_key() -> str:
    env = load_env()
    key = env.get('JQUANTS_API_KEY') or os.environ.get('JQUANTS_API_KEY', '')
    if not key:
        cfg = Path.home() / '.jquants_config.json'
        if cfg.exists():
            key = json.loads(cfg.read_text()).get('jquants_api_key', '')
    return key

def fetch_daily_5y(code4: str, api_key: str, years: int = 5, retries: int = 3) -> list:
    code5     = code4 + '0'
    date_from = (datetime.now() - timedelta(days=years * 366)).strftime('%Y%m%d')
    date_to   = datetime.now().strftime('%Y%m%d')
    url = (f'https://api.jquants.com/v2/equities/bars/daily'
           f'?code={code5}&from={date_from}&to={date_to}')
    headers = {'x-api-key': api_key}

    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 429:
                time.sleep(SLEEP_429 * (attempt + 1))
                continue
            if resp.status_code in (401, 403):
                return []
            if resp.status_code != 200:
                time.sleep(2)
                continue
            return resp.json().get('data', [])
        except Exception:
            time.sleep(2)
    return []

def load_master() -> dict:
    master_path = DATA_DIR / 'equity_master_cache.json'
    if not master_path.exists():
        return {}
    data = json.loads(master_path.read_text(encoding='utf-8'))
    items = data.get('items', data) if isinstance(data, dict) else data
    result = {}
    for item in items:
        code = item.get('Code', '')
        code4 = code[:4] if len(code) >= 4 else code
        result.setdefault(code4, item)
    return result

def calc_gain(bars: list) -> dict | None:
    if len(bars) < 50:
        return None

    def gp(bar, adj, raw):
        # V2 API: AdjC/AdjH/AdjL/AdjO/AdjVo, C/H/L/O/Vo
        v = bar.get(adj)
        if v is None or v == 0:
            v = bar.get(raw, 0)
        try:
            return float(v)
        except Exception:
            return 0.0

    closes = [gp(b, 'AdjC', 'C') for b in bars]
    lows   = [gp(b, 'AdjL', 'L') for b in bars]
    highs  = [gp(b, 'AdjH', 'H') for b in bars]

    valid_lows  = [(i, v) for i, v in enumerate(lows)  if v > 0]
    valid_highs = [(i, v) for i, v in enumerate(highs) if v > 0]
    valid_c0    = next((v for v in closes if v > 0), None)

    if not valid_lows or not valid_highs or not valid_c0:
        return None

    lo_idx, lo = min(valid_lows,  key=lambda x: x[1])
    hi_idx, hi = max(valid_highs, key=lambda x: x[1])
    c1 = next((v for v in reversed(closes) if v > 0), 0)

    if lo <= 0:
        return None

    gain_lh = (hi - lo) / lo * 100
    gain_cc = (c1 - valid_c0) / valid_c0 * 100

    vols      = [b.get('AdjVo', b.get('Vo', 0)) or 0 for b in bars]
    n         = len(bars)
    vol_early = sum(vols[:n//4]) / max(n//4, 1)
    vol_late  = sum(vols[3*n//4:]) / max(n - 3*n//4, 1)
    vol_ratio = vol_late / vol_early if vol_early > 0 else 0

    return {
        'lo': lo, 'hi': hi, 'c0': valid_c0, 'c1': c1,
        'gain_lh': gain_lh, 'gain_cc': gain_cc,
        'date_lo': bars[lo_idx].get('Date', ''),
        'date_hi': bars[hi_idx].get('Date', ''),
        'vol_ratio': vol_ratio,
        'bars': len(bars),
    }

def process_one(code4, api_key, master, years, min_gain):
    bars = fetch_daily_5y(code4, api_key, years)
    g = calc_gain(bars)
    # gain_cc = 期初終値→現在終値 (「5年で3倍」の正しい定義)
    if g is None or g['gain_cc'] < min_gain:
        return None
    info = master.get(code4, {})
    return {
        'code':      code4,
        'name':      info.get('CoName', ''),
        'sector':    info.get('S17Nm', ''),
        'market':    info.get('MktNm', ''),
        'lo':        round(g['lo'], 1),
        'hi':        round(g['hi'], 1),
        'c0':        round(g['c0'], 1),
        'c1':        round(g['c1'], 1),
        'gain_lh':   round(g['gain_lh'], 1),
        'gain_cc':   round(g['gain_cc'], 1),
        'date_lo':   g['date_lo'],
        'date_hi':   g['date_hi'],
        'vol_ratio': round(g['vol_ratio'], 2),
        'bars':      g['bars'],
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--years',   type=int,   default=YEARS)
    parser.add_argument('--min',     type=float, default=MIN_GAIN)
    parser.add_argument('--workers', type=int,   default=10)
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        print('ERROR: JQUANTS_API_KEY not found'); return

    master    = load_master()
    all_codes = sorted(k for k in master.keys() if k.isdigit() and len(k) == 4)
    if not all_codes:
        all_codes = sorted(
            f.stem.replace('_daily','')
            for f in CSV_DIR.glob('*_daily.csv')
            if f.stem.replace('_daily','').isdigit()
        )

    total = len(all_codes)
    mult  = args.min / 100 + 1
    print(f'対象: {total}件  閾値: {args.min:.0f}%({mult:.1f}倍)  期間: {args.years}年  並列: {args.workers}')
    print(f'開始: {datetime.now().strftime("%H:%M:%S")}')
    print('-' * 60)

    winners = []
    done    = 0
    t0      = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        fmap = {ex.submit(process_one, c, api_key, master, args.years, args.min): c
                for c in all_codes}
        for fut in as_completed(fmap):
            done += 1
            r = fut.result()
            if r:
                winners.append(r)
            if done % 200 == 0 or done == total:
                elapsed = time.time() - t0
                rem = elapsed / done * (total - done) if done < total else 0
                print(f'  [{done:4d}/{total}] 該当:{len(winners):3d}件  残り:{rem/60:.1f}分')
                sys.stdout.flush()

    winners.sort(key=lambda x: -x['gain_lh'])

    print(f'\n{"="*110}')
    print(f'  {args.years}年で{mult:.0f}倍以上 (+{args.min:.0f}%超): {len(winners)}件')
    print(f'{"="*110}')
    hdr = f"{'順':>3}  {'Code':<6}  {'名称':<22}  {'セクター':<18}  {'安値':>8}  {'高値':>8}  {'最大上昇':>8}  {'期初→現在':>9}  {'出来高倍':>6}  {'高値日'}"
    print(hdr)
    print('-' * 110)
    for i, r in enumerate(winners, 1):
        print(f"{i:>3}  {r['code']:<6}  {r['name']:<22}  {r['sector']:<18}  "
              f"{r['lo']:>8,.0f}  {r['hi']:>8,.0f}  "
              f"{r['gain_lh']:>7.0f}%  {r['gain_cc']:>8.0f}%  "
              f"{r['vol_ratio']:>5.1f}x  {r['date_hi']}")

    print('\n=== セクター分布 ===')
    cnt = {}
    for r in winners:
        s = r['sector'] or 'Unknown'
        cnt[s] = cnt.get(s, 0) + 1
    for s, c in sorted(cnt.items(), key=lambda x: -x[1]):
        print(f"  {s:<25} {c:3d}件  {'█'*min(c,40)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / f'{args.years}y_winners.csv'
    with open(out_file, 'w', newline='', encoding='utf-8-sig') as f:
        fields = ['code','name','sector','market','lo','hi','c0','c1',
                  'gain_lh','gain_cc','date_lo','date_hi','vol_ratio','bars']
        csv.DictWriter(f, fieldnames=fields).writeheader()
        csv.DictWriter(f, fieldnames=fields).writerows(winners)
    print(f'\n保存完了: {out_file}  ({len(winners)}件)')
    sys.stdout.flush()

if __name__ == '__main__':
    main()

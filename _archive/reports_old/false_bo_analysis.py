import sys, time, json, csv, statistics
sys.path.insert(0, r'C:\Users\yohei\Documents\invest-system-github\.claude\worktrees\cranky-nash')
import stock_mcp_server as s

winners = []
with open('reports/5y_winners.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        winners.append(row)

def sma_v(closes, idx, n):
    if idx < n - 1: return None
    return sum(closes[idx-n+1:idx+1]) / n

def analyze_first_77_only(code, bars, gain5y):
    closes = [b.get('AdjC') or b.get('C') or 0 for b in bars]
    dates = [b.get('Date','') for b in bars]
    vols = [b.get('AdjVo') or b.get('V') or 0 for b in bars]
    if len(closes) < 220: return None
    nz = [(i, c) for i, c in enumerate(closes) if c > 0]
    if not nz: return None
    lo_val = min(c for _,c in nz)
    lo_idx = next(i for i,c in nz if c == lo_val)
    
    first_event = None
    prev_77 = False
    
    for idx in range(max(220, lo_idx), len(closes)-91):
        c = closes[idx]
        if c <= 0: prev_77=False; continue
        s50 = sma_v(closes, idx, 50)
        s150 = sma_v(closes, idx, 150)
        s200 = sma_v(closes, idx, 200)
        if None in (s50, s150, s200): prev_77=False; continue
        s200_20ago = sma_v(closes, idx-20, 200)
        if s200_20ago is None: prev_77=False; continue
        conds = [c>s50, c>s150, c>s200, s50>s150, s50>s200, s200>s200_20ago]
        is_77 = all(conds)
        
        if is_77 and not prev_77 and first_event is None:
            vol_avg20 = sum(vols[max(0,idx-20):idx]) / 20 if idx >= 20 else vols[idx]
            vol_ratio_entry = vols[idx] / vol_avg20 if vol_avg20 > 0 else 1
            max_vol_idx = max(range(max(0,idx-30), idx+1), key=lambda i: vols[i])
            max_vol_ratio = vols[max_vol_idx] / vol_avg20 if vol_avg20 > 0 else 1
            max_vol_offset = max_vol_idx - idx
            max_vol_date = dates[max_vol_idx]
            ret_10d_before = (c - closes[max(0,idx-10)]) / closes[max(0,idx-10)] * 100 if closes[max(0,idx-10)]>0 else 0
            ret_20d_before = (c - closes[max(0,idx-20)]) / closes[max(0,idx-20)] * 100 if closes[max(0,idx-20)]>0 else 0
            gain_from_lo = (c - lo_val) / lo_val * 100
            idx90 = idx + 90
            is_77_90d = False
            if idx90 < len(closes):
                c90 = closes[idx90]
                s50_90 = sma_v(closes, idx90, 50)
                s150_90 = sma_v(closes, idx90, 150)
                s200_90 = sma_v(closes, idx90, 200)
                s200_20ago_90 = sma_v(closes, idx90-20, 200)
                if None not in (s50_90,s150_90,s200_90,s200_20ago_90) and c90>0:
                    conds90 = [c90>s50_90,c90>s150_90,c90>s200_90,s50_90>s150_90,s50_90>s200_90,s200_90>s200_20ago_90]
                    is_77_90d = all(conds90)
            ret_30d = (closes[min(idx+30,len(closes)-1)] - c) / c * 100
            ret_90d = (closes[idx90] - c) / c * 100 if idx90 < len(closes) and closes[idx90]>0 else 0
            first_event = {
                'code': code, 'gain5y': gain5y,
                'date': dates[idx], 'price': round(c,1),
                'lo_val': round(lo_val,1), 'gain_from_lo': round(gain_from_lo,1),
                'vol_ratio_entry': round(vol_ratio_entry,2),
                'max_vol_ratio': round(max_vol_ratio,2),
                'max_vol_offset': max_vol_offset,
                'max_vol_date': max_vol_date,
                'ret_10d_before': round(ret_10d_before,1),
                'ret_20d_before': round(ret_20d_before,1),
                'ret_30d': round(ret_30d,1),
                'ret_90d': round(ret_90d,1),
                'sustained': is_77_90d,
            }
            break
        prev_77 = is_77
    return first_event

import random
random.seed(42)
low_gain = [w for w in winners if 200 <= float(w['gain_cc']) <= 400]
high_gain = [w for w in winners if float(w['gain_cc']) > 400]
sample = random.sample(low_gain, min(30, len(low_gain))) + random.sample(high_gain, min(25, len(high_gain)))

results = []
for w in sample:
    code = w['code']
    gain5y = float(w['gain_cc'])
    bars = s._fetch_daily(code, days=3650)
    ev = analyze_first_77_only(code, bars, gain5y)
    if ev:
        results.append(ev)
    time.sleep(0.05)

false_r = [r for r in results if not r['sustained']]
sust_r = [r for r in results if r['sustained']]
print(f'First-77 analysis: {len(results)} stocks, False={len(false_r)}, Sustained={len(sust_r)}')

if false_r and sust_r:
    print('')
    print(f'                         False({len(false_r)})   Sustained({len(sust_r)})')
    print(f'entry vol ratio:         {statistics.mean([r["vol_ratio_entry"] for r in false_r]):.2f}x    {statistics.mean([r["vol_ratio_entry"] for r in sust_r]):.2f}x')
    print(f'max vol(30d window):     {statistics.mean([r["max_vol_ratio"] for r in false_r]):.2f}x    {statistics.mean([r["max_vol_ratio"] for r in sust_r]):.2f}x')
    print(f'max vol offset:          {statistics.mean([r["max_vol_offset"] for r in false_r]):.1f}d    {statistics.mean([r["max_vol_offset"] for r in sust_r]):.1f}d')
    print(f'ret -10d before:         {statistics.mean([r["ret_10d_before"] for r in false_r]):.1f}%    {statistics.mean([r["ret_10d_before"] for r in sust_r]):.1f}%')
    print(f'ret -20d before:         {statistics.mean([r["ret_20d_before"] for r in false_r]):.1f}%    {statistics.mean([r["ret_20d_before"] for r in sust_r]):.1f}%')
    print(f'gain from lo:            {statistics.mean([r["gain_from_lo"] for r in false_r]):.1f}%    {statistics.mean([r["gain_from_lo"] for r in sust_r]):.1f}%')
    print(f'ret +30d:                {statistics.mean([r["ret_30d"] for r in false_r]):.1f}%    {statistics.mean([r["ret_30d"] for r in sust_r]):.1f}%')
    print(f'ret +90d:                {statistics.mean([r["ret_90d"] for r in false_r]):.1f}%    {statistics.mean([r["ret_90d"] for r in sust_r]):.1f}%')

from collections import Counter
def bucket(offset):
    if offset <= -10: return '-10d+'
    elif offset <= -5: return '-5to-10d'
    elif offset == -4: return '-4d'
    elif offset == -3: return '-3d'
    elif offset == -2: return '-2d'
    elif offset == -1: return '-1d'
    elif offset == 0: return 'same'
    else: return '+1d+'
false_buckets = Counter([bucket(r['max_vol_offset']) for r in false_r])
sust_buckets = Counter([bucket(r['max_vol_offset']) for r in sust_r])
all_buckets = ['-10d+','-5to-10d','-4d','-3d','-2d','-1d','same','+1d+']
print('')
print(f'timing      | False | Sust | FalseRate')
for b in all_buckets:
    f_cnt = false_buckets.get(b, 0)
    s_cnt = sust_buckets.get(b, 0)
    total = f_cnt + s_cnt
    ratio = f_cnt/total*100 if total>0 else 0
    print(f'{b:12}| {f_cnt:5} | {s_cnt:4} | {ratio:.0f}%')

print('')
print('--- high vol false (max_vol>=3x) ---')
hvf = sorted([r for r in false_r if r['max_vol_ratio']>=3], key=lambda x: x['max_vol_ratio'], reverse=True)[:8]
for r in hvf:
    print(f"  {r['code']} {r['date']} maxvol={r['max_vol_ratio']:.1f}x(t{r['max_vol_offset']:+d}d,{r['max_vol_date']}) entryvol={r['vol_ratio_entry']:.2f}x ret10b={r['ret_10d_before']:+.1f}% ret30={r['ret_30d']:+.1f}%")

print('')
print('--- high vol sustained (max_vol>=3x) ---')
hvs = sorted([r for r in sust_r if r['max_vol_ratio']>=3], key=lambda x: x['max_vol_ratio'], reverse=True)[:5]
for r in hvs:
    print(f"  {r['code']} {r['date']} maxvol={r['max_vol_ratio']:.1f}x(t{r['max_vol_offset']:+d}d,{r['max_vol_date']}) entryvol={r['vol_ratio_entry']:.2f}x ret10b={r['ret_10d_before']:+.1f}% ret30={r['ret_30d']:+.1f}%")

with open('reports/false_bo_results.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f'\nSaved to reports/false_bo_results.json')

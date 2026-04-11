"""
フォルスブレイクアウト分析 v2
修正点:
- 5y_winners.csvのdate_lo（5年間の正しい最安値日）を使用（10年絶対最安値の誤りを修正）
- 全384銘柄を分析（前回は55銘柄サンプルのみ）
- 追加指標: SMA200の傾き、安値からの経過日数、RS26w相当
"""
import sys, time, json, csv, statistics, datetime
sys.path.insert(0, r'C:\Users\yohei\Documents\invest-system-github\.claude\worktrees\cranky-nash')
import stock_mcp_server as s

winners = []
with open('reports/5y_winners.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        winners.append(row)
print(f'Total: {len(winners)} stocks')

def sma_v(closes, idx, n):
    if idx < n - 1: return None
    return sum(closes[idx-n+1:idx+1]) / n

def analyze_stock(w, bars):
    code = w['code']
    gain5y = float(w['gain_cc'])
    date_lo_str = w['date_lo']   # CSVの正しい最安値日
    lo_price = float(w['lo'])

    closes = [b.get('AdjC') or b.get('C') or 0 for b in bars]
    dates = [b.get('Date', '') for b in bars]
    vols = [b.get('AdjVo') or b.get('V') or 0 for b in bars]

    if len(closes) < 220: return None

    # date_loのインデックスを探す（±3日の余裕）
    lo_idx = None
    for i, d in enumerate(dates):
        if d == date_lo_str:
            lo_idx = i
            break
    if lo_idx is None:
        # 近い日付を探す
        for i, d in enumerate(dates):
            if abs((datetime.datetime.strptime(d,'%Y-%m-%d') -
                    datetime.datetime.strptime(date_lo_str,'%Y-%m-%d')).days) <= 5:
                lo_idx = i
                break
    if lo_idx is None:
        return None

    # lo_idx以降の最初の7/7達成を探す（最低でもlo_idxから220日後まで待つ）
    search_start = max(220, lo_idx)
    first_event = None
    prev_77 = False

    for idx in range(search_start, len(closes) - 91):
        c = closes[idx]
        if c <= 0: prev_77 = False; continue

        s50 = sma_v(closes, idx, 50)
        s150 = sma_v(closes, idx, 150)
        s200 = sma_v(closes, idx, 200)
        if None in (s50, s150, s200): prev_77 = False; continue
        s200_20ago = sma_v(closes, idx - 20, 200)
        if s200_20ago is None: prev_77 = False; continue

        # SMA200の傾き（直近20日での変化率）
        sma200_slope_pct = (s200 - s200_20ago) / s200_20ago * 100 if s200_20ago > 0 else 0

        conds = [c > s50, c > s150, c > s200, s50 > s150, s50 > s200, s200 > s200_20ago]
        is_77 = all(conds)

        if is_77 and not prev_77 and first_event is None:
            # --- 出来高指標 ---
            vol_avg20 = sum(vols[max(0, idx - 20):idx]) / 20 if idx >= 20 else vols[idx]
            vol_ratio_entry = vols[idx] / vol_avg20 if vol_avg20 > 0 else 1.0

            # 過去30日の最大出来高とそのタイミング
            max_vol_idx = max(range(max(0, idx - 30), idx + 1), key=lambda i: vols[i])
            max_vol_ratio = vols[max_vol_idx] / vol_avg20 if vol_avg20 > 0 else 1.0
            max_vol_offset = max_vol_idx - idx  # 負=前, 0=当日

            # --- 価格指標 ---
            ret_5d_before  = (c - closes[max(0,idx-5)])  / closes[max(0,idx-5)]  * 100 if closes[max(0,idx-5)]>0 else 0
            ret_10d_before = (c - closes[max(0,idx-10)]) / closes[max(0,idx-10)] * 100 if closes[max(0,idx-10)]>0 else 0
            ret_20d_before = (c - closes[max(0,idx-20)]) / closes[max(0,idx-20)] * 100 if closes[max(0,idx-20)]>0 else 0

            # 最安値（CSV基準）からの上昇率
            gain_from_lo = (c - lo_price) / lo_price * 100

            # 最安値からの経過営業日数
            days_from_lo = idx - lo_idx

            # SMA50とpriceの乖離率（大きい=買われすぎ）
            price_sma50_gap = (c - s50) / s50 * 100 if s50 > 0 else 0

            # 52週高値比（7/7条件の一つ: 高値の75%以上）
            hi52 = max(c2 for c2 in closes[max(0,idx-252):idx+1] if c2 > 0) if idx >= 252 else max(c2 for c2 in closes[:idx+1] if c2>0)
            price_vs_hi52 = c / hi52 * 100 if hi52 > 0 else 0

            # --- 90日後判定 ---
            idx90 = idx + 90
            is_77_90d = False
            if idx90 < len(closes):
                c90 = closes[idx90]
                s50_90  = sma_v(closes, idx90, 50)
                s150_90 = sma_v(closes, idx90, 150)
                s200_90 = sma_v(closes, idx90, 200)
                s200_20ago_90 = sma_v(closes, idx90 - 20, 200)
                if None not in (s50_90, s150_90, s200_90, s200_20ago_90) and c90 > 0:
                    conds90 = [c90>s50_90, c90>s150_90, c90>s200_90,
                               s50_90>s150_90, s50_90>s200_90, s200_90>s200_20ago_90]
                    is_77_90d = all(conds90)

            ret_30d = (closes[min(idx+30, len(closes)-1)] - c) / c * 100
            ret_60d = (closes[min(idx+60, len(closes)-1)] - c) / c * 100
            ret_90d = (closes[idx90] - c) / c * 100 if idx90 < len(closes) and closes[idx90] > 0 else 0

            # 最悪ドローダウン（30日以内）
            max_dd_30d = 0
            for j in range(idx+1, min(idx+31, len(closes))):
                if closes[j] > 0:
                    dd = (closes[j] - c) / c * 100
                    if dd < max_dd_30d:
                        max_dd_30d = dd

            first_event = {
                'code': code,
                'gain5y': gain5y,
                'date': dates[idx],
                'year': int(dates[idx][:4]),
                'price': round(c, 1),
                'lo_price': lo_price,
                'lo_date': date_lo_str,
                'gain_from_lo': round(gain_from_lo, 1),
                'days_from_lo': days_from_lo,

                # 出来高
                'vol_ratio_entry': round(vol_ratio_entry, 2),
                'max_vol_ratio': round(max_vol_ratio, 2),
                'max_vol_offset': max_vol_offset,
                'max_vol_date': dates[max_vol_idx],

                # 価格モメンタム（達成前）
                'ret_5d_before': round(ret_5d_before, 1),
                'ret_10d_before': round(ret_10d_before, 1),
                'ret_20d_before': round(ret_20d_before, 1),

                # 構造指標
                'sma200_slope': round(sma200_slope_pct, 3),
                'price_sma50_gap': round(price_sma50_gap, 1),
                'price_vs_hi52': round(price_vs_hi52, 1),

                # 結果
                'ret_30d': round(ret_30d, 1),
                'ret_60d': round(ret_60d, 1),
                'ret_90d': round(ret_90d, 1),
                'max_dd_30d': round(max_dd_30d, 1),
                'sustained': is_77_90d,
            }
            break
        prev_77 = is_77

    return first_event

# 全384銘柄処理
results = []
errors = []
for i, w in enumerate(winners):
    code = w['code']
    try:
        bars = s._fetch_daily(code, days=3650)
        ev = analyze_stock(w, bars)
        if ev:
            results.append(ev)
    except Exception as e:
        errors.append((code, str(e)))
    time.sleep(0.05)
    if (i+1) % 50 == 0:
        print(f'  {i+1}/384 done... results={len(results)}, errors={len(errors)}')

print(f'\nDone: {len(results)} results, {len(errors)} errors')

# 保存
with open('reports/false_bo_v2_results.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print('Saved to reports/false_bo_v2_results.json')

# ==== 集計 ====
false_r = [r for r in results if not r['sustained']]
sust_r  = [r for r in results if r['sustained']]
total = len(results)
print(f'\n=== SUMMARY ===')
print(f'Total: {total}, False={len(false_r)} ({len(false_r)/total*100:.1f}%), Sustained={len(sust_r)} ({len(sust_r)/total*100:.1f}%)')

def avg(lst): return round(statistics.mean(lst), 2) if lst else 0
def med(lst): return round(statistics.median(lst), 2) if lst else 0

print(f'\n{"Metric":<30} {"False":>10} {"Sustained":>12}')
print('-' * 55)
metrics = [
    ('vol_ratio_entry', '達成日出来高比率'),
    ('max_vol_ratio', '過去30d最大出来高'),
    ('max_vol_offset', '最大出来高タイミング(日)'),
    ('ret_5d_before', '達成前5日リターン%'),
    ('ret_10d_before', '達成前10日リターン%'),
    ('ret_20d_before', '達成前20日リターン%'),
    ('gain_from_lo', '安値からの上昇率%'),
    ('days_from_lo', '安値からの経過日数'),
    ('sma200_slope', 'SMA200傾き%/20d'),
    ('price_sma50_gap', 'price-SMA50乖離率%'),
    ('price_vs_hi52', '52週高値比%'),
    ('ret_30d', '30日後リターン%'),
    ('ret_60d', '60日後リターン%'),
    ('ret_90d', '90日後リターン%'),
    ('max_dd_30d', '30日最大DD%'),
]
for key, label in metrics:
    fv = [r[key] for r in false_r if r.get(key) is not None]
    sv = [r[key] for r in sust_r if r.get(key) is not None]
    print(f'{label:<30} {avg(fv):>10} {avg(sv):>12}')

# 出来高タイミング別フォルス率
from collections import Counter
def bucket(offset):
    if offset <= -20: return '<=−20d'
    elif offset <= -10: return '−11〜−20d'
    elif offset <= -5:  return '−5〜−10d'
    elif offset == -4:  return '−4d'
    elif offset == -3:  return '−3d'
    elif offset == -2:  return '−2d'
    elif offset == -1:  return '−1d'
    elif offset == 0:   return '当日'
    else:               return '+1d以降'
fb = Counter([bucket(r['max_vol_offset']) for r in false_r])
sb = Counter([bucket(r['max_vol_offset']) for r in sust_r])
order = ['<=−20d','−11〜−20d','−5〜−10d','−4d','−3d','−2d','−1d','当日','+1d以降']
print(f'\n{"タイミング":<14}| False | Sust | FalseRate | N')
for b in order:
    f_cnt = fb.get(b, 0)
    s_cnt = sb.get(b, 0)
    n = f_cnt + s_cnt
    rate = f_cnt/n*100 if n > 0 else 0
    print(f'{b:<14}| {f_cnt:5} | {s_cnt:4} | {rate:7.1f}%  | {n}')

# 達成前10日リターン別フォルス率
print(f'\n{"ret10d_before":<20}| False | Sust | FalseRate')
buckets_10d = [('<-5%', lambda x: x < -5), ('-5〜0%', lambda x: -5 <= x < 0),
               ('0〜3%', lambda x: 0 <= x < 3), ('3〜7%', lambda x: 3 <= x < 7),
               ('7〜15%', lambda x: 7 <= x < 15), ('>15%', lambda x: x >= 15)]
for label, fn in buckets_10d:
    fc = sum(1 for r in false_r if fn(r['ret_10d_before']))
    sc = sum(1 for r in sust_r if fn(r['ret_10d_before']))
    n = fc + sc
    rate = fc/n*100 if n > 0 else 0
    print(f'{label:<20}| {fc:5} | {sc:4} | {rate:7.1f}%  (n={n})')

# price-SMA50乖離率別フォルス率
print(f'\n{"price_sma50_gap":<20}| False | Sust | FalseRate')
buckets_gap = [('<0%', lambda x: x < 0), ('0〜5%', lambda x: 0 <= x < 5),
               ('5〜10%', lambda x: 5 <= x < 10), ('10〜20%', lambda x: 10 <= x < 20),
               ('>20%', lambda x: x >= 20)]
for label, fn in buckets_gap:
    fc = sum(1 for r in false_r if fn(r['price_sma50_gap']))
    sc = sum(1 for r in sust_r if fn(r['price_sma50_gap']))
    n = fc + sc
    rate = fc/n*100 if n > 0 else 0
    print(f'{label:<20}| {fc:5} | {sc:4} | {rate:7.1f}%  (n={n})')

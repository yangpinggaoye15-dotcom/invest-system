"""
フォルスブレイクアウト分析 v3
【判断基準を修正】
  誤: 90日後に7/7を維持しているか
  正: エントリー後にターゲット(+20%)を損切り(-7%)より先に達成したか

ロジック:
  entry_price = 7/7達成日の終値
  stop       = entry × (1 - stop_pct)   # デフォルト7%
  target1    = entry × (1 + target_pct) # デフォルト20%
  
  日足で逐次チェック:
    close <= stop  → STOP_LOSS (失敗)
    close >= target1 → TARGET_HIT (成功)
  90日経過しても未決 → TIMEOUT (保有継続 or 引き分け扱い)
"""
import sys, time, json, csv, statistics
sys.path.insert(0, r'C:\Users\yohei\Documents\invest-system-github\.claude\worktrees\cranky-nash')
import stock_mcp_server as s

STOP_PCT   = 0.07   # 損切り -7%
TARGET_PCT = 0.20   # 目標  +20%
HOLD_DAYS  = 90     # 最大保有日数

winners = []
with open('reports/5y_winners.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        winners.append(row)

def sma_v(closes, idx, n):
    if idx < n - 1: return None
    return sum(closes[idx-n+1:idx+1]) / n

def analyze_stock(w, bars):
    code      = w['code']
    gain5y    = float(w['gain_cc'])
    date_lo   = w['date_lo']
    lo_price  = float(w['lo'])

    closes = [b.get('AdjC') or b.get('C') or 0 for b in bars]
    dates  = [b.get('Date','') for b in bars]
    vols   = [b.get('AdjVo') or b.get('V') or 0 for b in bars]
    if len(closes) < 220: return None

    # date_lo のインデックスを探す
    lo_idx = None
    for i, d in enumerate(dates):
        if d == date_lo:
            lo_idx = i
            break
    if lo_idx is None:
        import datetime
        for i, d in enumerate(dates):
            try:
                if abs((datetime.datetime.strptime(d,'%Y-%m-%d') -
                        datetime.datetime.strptime(date_lo,'%Y-%m-%d')).days) <= 5:
                    lo_idx = i; break
            except: pass
    if lo_idx is None: return None

    # lo_idx 以降の最初の7/7達成を探す
    first_event = None
    prev_77 = False

    for idx in range(max(220, lo_idx), len(closes) - HOLD_DAYS - 1):
        c = closes[idx]
        if c <= 0: prev_77 = False; continue

        s50  = sma_v(closes, idx, 50)
        s150 = sma_v(closes, idx, 150)
        s200 = sma_v(closes, idx, 200)
        if None in (s50, s150, s200): prev_77 = False; continue
        s200_20 = sma_v(closes, idx-20, 200)
        if s200_20 is None: prev_77 = False; continue

        conds  = [c>s50, c>s150, c>s200, s50>s150, s50>s200, s200>s200_20]
        is_77  = all(conds)
        sma200_slope = (s200 - s200_20) / s200_20 * 100 if s200_20 > 0 else 0

        if is_77 and not prev_77 and first_event is None:
            entry = c
            stop   = entry * (1 - STOP_PCT)
            target = entry * (1 + TARGET_PCT)

            vol_avg20 = sum(vols[max(0,idx-20):idx]) / 20 if idx >= 20 else vols[idx]
            vol_entry = vols[idx] / vol_avg20 if vol_avg20 > 0 else 1.0
            max_vol_idx = max(range(max(0,idx-30), idx+1), key=lambda i: vols[i])
            max_vol     = vols[max_vol_idx] / vol_avg20 if vol_avg20 > 0 else 1.0
            max_vol_off = max_vol_idx - idx

            ret_5d  = (c - closes[max(0,idx-5)])  / closes[max(0,idx-5)]  * 100 if closes[max(0,idx-5)]>0 else 0
            ret_10d = (c - closes[max(0,idx-10)]) / closes[max(0,idx-10)] * 100 if closes[max(0,idx-10)]>0 else 0
            gap_sma50 = (c - s50) / s50 * 100 if s50 > 0 else 0

            # ターゲット/損切り到達チェック
            outcome     = 'TIMEOUT'
            outcome_day = HOLD_DAYS
            outcome_ret = 0.0
            max_ret     = 0.0
            min_ret     = 0.0

            for j in range(1, HOLD_DAYS + 1):
                jdx = idx + j
                if jdx >= len(closes): break
                pj = closes[jdx]
                if pj <= 0: continue
                ret_j = (pj - entry) / entry * 100
                if ret_j > max_ret: max_ret = ret_j
                if ret_j < min_ret: min_ret = ret_j

                if outcome == 'TIMEOUT':
                    if pj <= stop:
                        outcome     = 'STOP_LOSS'
                        outcome_day = j
                        outcome_ret = round(ret_j, 1)
                    elif pj >= target:
                        outcome     = 'TARGET_HIT'
                        outcome_day = j
                        outcome_ret = round(ret_j, 1)

            if outcome == 'TIMEOUT':
                outcome_ret = round((closes[idx + HOLD_DAYS] - entry) / entry * 100, 1) if (idx+HOLD_DAYS) < len(closes) else 0

            first_event = {
                'code': code, 'gain5y': gain5y,
                'date': dates[idx], 'year': int(dates[idx][:4]),
                'price': round(entry, 1),
                'lo_date': date_lo, 'lo_price': lo_price,
                'gain_from_lo': round((entry - lo_price) / lo_price * 100, 1),
                'days_from_lo': idx - lo_idx,

                # 出来高
                'vol_entry': round(vol_entry, 2),
                'max_vol': round(max_vol, 2),
                'max_vol_off': max_vol_off,

                # 価格モメンタム
                'ret_5d_before':  round(ret_5d,  1),
                'ret_10d_before': round(ret_10d, 1),
                'gap_sma50':      round(gap_sma50, 1),
                'sma200_slope':   round(sma200_slope, 3),

                # 結果
                'outcome':      outcome,          # TARGET_HIT / STOP_LOSS / TIMEOUT
                'outcome_day':  outcome_day,
                'outcome_ret':  outcome_ret,
                'max_ret_90d':  round(max_ret, 1),
                'min_ret_90d':  round(min_ret, 1),
            }
            break
        prev_77 = is_77
    return first_event

# 全384銘柄処理
results = []
for i, w in enumerate(winners):
    try:
        bars = s._fetch_daily(w['code'], days=3650)
        ev   = analyze_stock(w, bars)
        if ev: results.append(ev)
    except: pass
    time.sleep(0.05)
    if (i+1) % 50 == 0:
        print(f'  {i+1}/384 done (results={len(results)})')

with open('reports/false_bo_v3_results.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f'\nDone: {len(results)} saved')

# ======================== 集計 ========================
hit  = [r for r in results if r['outcome'] == 'TARGET_HIT']
stop = [r for r in results if r['outcome'] == 'STOP_LOSS']
tout = [r for r in results if r['outcome'] == 'TIMEOUT']
n    = len(results)

print(f'\n=== 全体 (n={n}) ===')
print(f'TARGET_HIT (+20%): {len(hit):3}件 ({len(hit)/n*100:.1f}%)')
print(f'STOP_LOSS  (-7%):  {len(stop):3}件 ({len(stop)/n*100:.1f}%)')
print(f'TIMEOUT    (90d):  {len(tout):3}件 ({len(tout)/n*100:.1f}%)')

if hit:
    print(f'\n TARGET_HIT 平均到達日数: {statistics.mean([r["outcome_day"] for r in hit]):.1f}日')
if stop:
    print(f' STOP_LOSS  平均到達日数: {statistics.mean([r["outcome_day"] for r in stop]):.1f}日')

def avg(lst, key): return round(statistics.mean([r[key] for r in lst]),2) if lst else 0
def med(lst, key): return round(statistics.median([r[key] for r in lst]),2) if lst else 0

print(f'\n{"指標":<25}  {"HIT":>8}  {"STOP":>8}  {"TIMEOUT":>8}')
print('-'*55)
for key, label in [('vol_entry','達成日出来高'),('max_vol','30d最大出来高'),
                   ('max_vol_off','最大出来高オフセット'),
                   ('ret_5d_before','前5日%'),('ret_10d_before','前10日%'),
                   ('gap_sma50','SMA50乖離%'),('sma200_slope','SMA200傾き'),
                   ('gain_from_lo','安値から%'),('days_from_lo','安値から日数')]:
    print(f'{label:<25}  {avg(hit,key):>8}  {avg(stop,key):>8}  {avg(tout,key):>8}')

# ---- 各指標のバケツ別ヒット率 ----
def bucket_analysis(label, fn_list, results):
    print(f'\n--- {label} ---')
    print(f'{"区分":<18}| HIT | STOP | TOUT | Hit率 | Stop率 |  n')
    for blabel, fn in fn_list:
        sub = [r for r in results if fn(r)]
        h = sum(1 for r in sub if r['outcome']=='TARGET_HIT')
        s = sum(1 for r in sub if r['outcome']=='STOP_LOSS')
        t = sum(1 for r in sub if r['outcome']=='TIMEOUT')
        nn = len(sub)
        hr = h/nn*100 if nn>0 else 0
        sr = s/nn*100 if nn>0 else 0
        print(f'{blabel:<18}| {h:3} | {s:4} | {t:4} | {hr:5.1f}% | {sr:6.1f}% | {nn}')

bucket_analysis('達成前10日リターン', [
    ('<-5%',    lambda r: r['ret_10d_before'] < -5),
    ('-5〜0%',  lambda r: -5 <= r['ret_10d_before'] < 0),
    ('0〜3%',   lambda r: 0  <= r['ret_10d_before'] < 3),
    ('3〜7%',   lambda r: 3  <= r['ret_10d_before'] < 7),
    ('7〜15%',  lambda r: 7  <= r['ret_10d_before'] < 15),
    ('>15%',    lambda r: r['ret_10d_before'] >= 15),
], results)

bucket_analysis('SMA50乖離率', [
    ('0〜5%',   lambda r: 0  <= r['gap_sma50'] < 5),
    ('5〜10%',  lambda r: 5  <= r['gap_sma50'] < 10),
    ('10〜20%', lambda r: 10 <= r['gap_sma50'] < 20),
    ('>20%',    lambda r: r['gap_sma50'] >= 20 and r['gap_sma50'] < 200),
], results)

bucket_analysis('達成日出来高', [
    ('<0.5倍',  lambda r: r['vol_entry'] < 0.5),
    ('0.5〜1倍',lambda r: 0.5 <= r['vol_entry'] < 1.0),
    ('1〜2倍',  lambda r: 1.0 <= r['vol_entry'] < 2.0),
    ('2〜5倍',  lambda r: 2.0 <= r['vol_entry'] < 5.0),
    ('>5倍',    lambda r: r['vol_entry'] >= 5.0),
], results)

bucket_analysis('最大出来高タイミング', [
    ('<=−20d',    lambda r: r['max_vol_off'] <= -20),
    ('−11〜−20d', lambda r: -20 < r['max_vol_off'] <= -11),
    ('−5〜−10d',  lambda r: -10 < r['max_vol_off'] <= -5),
    ('−1〜−4d',   lambda r: -4  < r['max_vol_off'] <= -1),  # ← 注目
    ('当日',       lambda r: r['max_vol_off'] == 0),
], results)

# 複合条件
bucket_analysis('複合条件', [
    ('ret10d<5% + gap<10%',          lambda r: r['ret_10d_before']<5 and r['gap_sma50']<10),
    ('ret10d<5% + gap<5%',           lambda r: r['ret_10d_before']<5 and r['gap_sma50']<5),
    ('ret10d>15% or gap>20%',        lambda r: r['ret_10d_before']>15 or (r['gap_sma50']>20 and r['gap_sma50']<200)),
    ('vol>5x',                       lambda r: r['vol_entry']>=5.0),
    ('ret10d<5% + gap<5% + vol<2x',  lambda r: r['ret_10d_before']<5 and r['gap_sma50']<5 and r['vol_entry']<2),
], results)

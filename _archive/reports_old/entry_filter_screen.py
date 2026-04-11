"""
最終エントリーフィルタースクリーニング
必須: 7/7 + gap_sma50<5% + RS50w>1.3
加点: std<2.0 + OBV<1.5 + 前10日<+5%
"""
import json, os, csv, statistics, sys
from datetime import datetime, timedelta

BASE = os.environ.get('INVEST_BASE_DIR', r'C:\Users\yohei\Documents\invest-system')
DATA_DIR = os.path.join(BASE, 'data')

def load_csv(code):
    """CSVファイルから日次データを読み込む"""
    path = os.path.join(DATA_DIR, f'{code}.csv')
    if not os.path.exists(path):
        return None, None
    dates, closes, highs, lows, vols = [], [], [], [], []
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                closes.append(float(row.get('Close', row.get('close', 0)) or 0))
                highs.append(float(row.get('High', row.get('high', 0)) or 0))
                lows.append(float(row.get('Low', row.get('low', 0)) or 0))
                vols.append(float(row.get('Volume', row.get('volume', 0)) or 0))
                dates.append(row.get('Date', row.get('date', '')))
            except:
                pass
    return dates, closes, highs, lows, vols

def sma(arr, n):
    if len(arr) < n: return None
    return sum(arr[-n:]) / n

def check_7_7(closes):
    """7/7 Minervini条件チェック"""
    if len(closes) < 200: return False
    price = closes[-1]
    s50 = sma(closes, 50)
    s150 = sma(closes, 150)
    s200 = sma(closes, 200)
    s200_prev = sma(closes[:-20], 200) if len(closes) >= 220 else None
    
    if None in [s50, s150, s200]: return False
    
    c1 = price > s150 and price > s200
    c2 = s150 > s200
    c3 = s200 > (s200_prev or 0) if s200_prev else True
    c4 = s50 > s150 and s50 > s200
    c5 = price > s50
    c6 = price > closes[-250] * 1.25 if len(closes) >= 250 else True  # 52wL+25%
    c7 = price >= max(closes[-252:]) * 0.75 if len(closes) >= 252 else True  # 52wH-25%
    
    return all([c1,c2,c3,c4,c5,c6,c7])

def calc_metrics(closes, vols, window=20):
    """gap_sma50, std, OBV比, RS50w, 前10日変化率を計算"""
    if len(closes) < 260: return None
    
    price = closes[-1]
    s50 = sma(closes, 50)
    if not s50: return None
    
    gap_sma50 = (price - s50) / s50 * 100
    
    # RS50w (250日前比)
    rs50w = price / closes[-251] if closes[-251] > 0 else 1.0
    
    # 前10日変化率
    ret10d = (price - closes[-11]) / closes[-11] * 100 if closes[-11] > 0 else 0
    
    # 直近20日の日次std
    cw = closes[-21:-1]  # 直前20日
    vw = vols[-21:-1]
    rets = [(cw[i]-cw[i-1])/cw[i-1]*100 for i in range(1,len(cw)) if cw[i-1]>0]
    daily_std = statistics.stdev(rets) if len(rets) > 1 else 99
    
    # OBV比（上昇日/下落日の出来高比）
    up_vol = sum(vw[i] for i in range(1, len(cw)) if cw[i] >= cw[i-1])
    dn_vol = sum(vw[i] for i in range(1, len(cw)) if cw[i] < cw[i-1])
    obv_ratio = up_vol / dn_vol if dn_vol > 0 else 2.0
    
    return {
        'gap_sma50': gap_sma50,
        'rs50w': rs50w,
        'ret10d': ret10d,
        'daily_std': daily_std,
        'obv_ratio': obv_ratio,
        'price': price,
        's50': s50,
    }

def main():
    # screen_full_results から 7/7 銘柄を取得
    sf_path = os.path.join(BASE, 'data', 'screen_full_results.json')
    if not os.path.exists(sf_path):
        print("screen_full_results.json not found")
        return
    
    with open(sf_path, encoding='utf-8') as f:
        sf_data = json.load(f)
    
    # 全銘柄ループ（passed=True のもの）
    passed_codes = []
    for code, info in sf_data.items():
        if isinstance(info, dict) and info.get('passed', False):
            passed_codes.append(code)
    
    print(f"7/7 passed: {len(passed_codes)} stocks")
    
    # 各銘柄で指標計算
    candidates = []
    target_codes = ['5803'] + passed_codes  # 5803を必ず含める
    
    for code in target_codes:
        dates, closes, highs, lows, vols = load_csv(code)
        if closes is None or len(closes) < 260:
            continue
        
        info = sf_data.get(code, {})
        name = info.get('name', code) if isinstance(info, dict) else code
        
        metrics = calc_metrics(closes, vols)
        if metrics is None:
            continue
        
        m = metrics
        is_7_7 = check_7_7(closes) if not info.get('passed', False) else True
        
        # フィルター評価
        f_gap = m['gap_sma50'] < 5.0
        f_rs = m['rs50w'] > 1.3
        f_ret10 = m['ret10d'] < 5.0
        f_std = m['daily_std'] < 2.0
        f_obv = m['obv_ratio'] < 1.5
        
        # 必須条件
        must_pass = is_7_7 and f_gap and f_rs
        
        # 加点
        bonus = sum([f_ret10, f_std, f_obv])
        
        row = {
            'code': code,
            'name': name[:20],
            'price': m['price'],
            'gap%': round(m['gap_sma50'], 1),
            'rs50w': round(m['rs50w'], 2),
            'ret10d': round(m['ret10d'], 1),
            'std': round(m['daily_std'], 2),
            'obv': round(m['obv_ratio'], 2),
            'must': must_pass,
            'bonus': bonus,
            'flag_gap': '✓' if f_gap else '✗',
            'flag_rs': '✓' if f_rs else '✗',
            'flag_ret': '✓' if f_ret10 else '-',
            'flag_std': '✓' if f_std else '-',
            'flag_obv': '✓' if f_obv else '-',
        }
        candidates.append(row)
    
    # 5803 個別表示
    print("\n=== 5803 フジクラ 評価 ===")
    fujikura = next((r for r in candidates if r['code'] == '5803'), None)
    if fujikura:
        f = fujikura
        print(f"  価格: ¥{f['price']:,.0f}  SMA50乖離: {f['gap%']}%  {'✓必須通過' if f['must'] else '✗必須失敗'}")
        print(f"  gap<5%  : {f['flag_gap']} ({f['gap%']}%)")
        print(f"  RS50w>1.3: {f['flag_rs']} ({f['rs50w']})")
        print(f"  前10日<5%: {f['flag_ret']} ({f['ret10d']}%)")
        print(f"  std<2.0  : {f['flag_std']} ({f['std']})")
        print(f"  OBV<1.5  : {f['flag_obv']} ({f['obv']})")
        print(f"  加点スコア: {f['bonus']}/3")
    else:
        print("  データなし")
    
    # 必須通過銘柄
    must_list = [r for r in candidates if r['must']]
    must_list.sort(key=lambda x: (-x['bonus'], -x['rs50w']))
    
    print(f"\n=== 最終フィルター通過銘柄 (gap<5% + RS50w>1.3 + 7/7) ===")
    print(f"該当: {len(must_list)} 銘柄\n")
    print(f"{'Code':6} {'Name':22} {'Price':>8} {'gap%':>6} {'RS50w':>6} {'ret10d':>7} {'std':>5} {'OBV':>5} {'加点':>4}")
    print("-" * 85)
    for r in must_list[:50]:
        bonus_str = "★★★" if r['bonus']==3 else "★★" if r['bonus']==2 else "★" if r['bonus']==1 else ""
        print(f"{r['code']:6} {r['name']:22} {r['price']:>8,.0f} {r['gap%']:>6.1f}% {r['rs50w']:>6.2f} {r['ret10d']:>6.1f}% {r['std']:>5.2f} {r['obv']:>5.2f} {bonus_str:>4}")

if __name__ == '__main__':
    main()

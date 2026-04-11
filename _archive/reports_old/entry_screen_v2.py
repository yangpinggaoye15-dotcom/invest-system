"""
最終エントリーフィルター v2（最適化版）スクリーニング
必須: 7/7 + gap_sma50<5% + OBV(15日)<1.0 + RS50w>1.3
加点: std<2.0 + 前10日<+5%
"""
import json, os, sys, time, statistics
from collections import defaultdict

GH_DIR   = r'C:\Users\yohei\Documents\invest-system-github'
BASE_DIR  = r'C:\Users\yohei\Documents\invest-system'
SF_JSON  = BASE_DIR + r'\data\screen_full_results.json'
OUT_FILE = GH_DIR + r'\reports\entry_screen_v2_result.txt'

sys.path.insert(0, GH_DIR)
import stock_mcp_server as s

def load_bars(code):
    try:
        bars = s._fetch_daily(code, days=400)  # ~1.5年分で十分（直近OBV + RS50w用）
        if not bars: return None
        result = []
        for b in bars:
            c = float(b.get('AdjC') or b.get('C') or 0)
            v = float(b.get('AdjVo') or b.get('Vo') or b.get('V') or 0)
            if c > 0:
                result.append({'date': b['Date'], 'close': c, 'vol': v})
        return result
    except:
        return None

def calc_metrics(bars):
    """gap_sma50, OBV15日, RS50w, std20日, 前10日変化率を計算"""
    if not bars or len(bars) < 260:
        return None
    closes = [b['close'] for b in bars]
    vols   = [b['vol']   for b in bars]
    n = len(closes)
    price = closes[-1]

    # SMA50
    sma50 = sum(closes[-50:]) / 50
    gap   = (price - sma50) / sma50 * 100

    # RS50w (250日前比)
    rs50w = price / closes[-251] if len(closes) >= 251 and closes[-251] > 0 else None

    # OBV15日（直前15日の上昇/下落出来高比）
    cw = closes[-16:-1]  # 直前15日
    vw = vols[-16:-1]
    up = sum(vw[i] for i in range(1, len(cw)) if cw[i] >= cw[i-1])
    dn = sum(vw[i] for i in range(1, len(cw)) if cw[i] <  cw[i-1])
    obv15 = up / dn if dn > 0 else 2.0

    # 前10日変化率
    ret10 = (price - closes[-11]) / closes[-11] * 100 if len(closes) >= 11 and closes[-11] > 0 else 0

    # 日次std（直前20日）
    cw20 = closes[-21:-1]
    rets = [(cw20[i]-cw20[i-1])/cw20[i-1]*100 for i in range(1,len(cw20)) if cw20[i-1]>0]
    std20 = statistics.stdev(rets) if len(rets) > 1 else 99

    return {
        'price': price,
        'sma50': sma50,
        'gap':   round(gap, 1),
        'rs50w': round(rs50w, 2) if rs50w else None,
        'obv15': round(obv15, 2),
        'ret10': round(ret10, 1),
        'std20': round(std20, 2),
    }

def main():
    # screen_full_results から 7/7 通過銘柄を取得
    with open(SF_JSON, encoding='utf-8') as f:
        sf = json.load(f)

    passed = [(v['code'], v['name'][:22]) for v in sf.values()
              if isinstance(v, dict) and v.get('passed')]
    print(f"7/7 PASS: {len(passed)}銘柄")

    candidates = []
    skip = 0
    done = 0

    for code, name in passed:
        bars = load_bars(code)
        if bars is None:
            skip += 1; done += 1; continue

        m = calc_metrics(bars)
        if m is None:
            skip += 1; done += 1; continue

        # 必須フィルター
        f_gap  = m['gap']   < 5.0
        f_obv  = m['obv15'] < 1.0
        f_rs   = (m['rs50w'] or 0) > 1.3

        # 加点
        f_std  = m['std20'] < 2.0
        f_ret  = m['ret10'] < 5.0
        bonus  = sum([f_std, f_ret])

        must = f_gap and f_obv and f_rs

        if must or (f_gap and f_rs):  # gap+RS通過は記録（OBV参考値として）
            candidates.append({
                'code': code, 'name': name,
                'must': must,
                'f_gap': f_gap, 'f_obv': f_obv, 'f_rs': f_rs,
                'bonus': bonus,
                **m
            })
        done += 1
        if done % 100 == 0:
            with open(OUT_FILE, 'w', encoding='utf-8') as f:
                f.write(f"Progress {done}/{len(passed)} candidates={len(candidates)}\n")
        time.sleep(0.03)

    # 出力
    must_list = [c for c in candidates if c['must']]
    near_list = [c for c in candidates if not c['must'] and c['f_gap'] and c['f_rs']]

    must_list.sort(key=lambda x: (-x['bonus'], x['obv15']))
    near_list.sort(key=lambda x: x['obv15'])

    lines = [f"処理完了: {done}/{len(passed)}  skip={skip}\n"]
    lines.append(f"=== 【全条件クリア】gap<5% + OBV15日<1.0 + RS50w>1.3 + 7/7: {len(must_list)}銘柄 ===")
    lines.append(f"{'Code':6} {'Name':23} {'Price':>8} {'gap%':>5} {'OBV15':>6} {'RS50w':>6} {'ret10':>6} {'std':>5} {'★':>3}")
    lines.append("-" * 80)
    for c in must_list:
        star = "★★" if c['bonus']==2 else "★" if c['bonus']==1 else ""
        lines.append(
            f"{c['code']:6} {c['name']:23} {c['price']:>8,.0f} {c['gap']:>4.1f}% "
            f"{c['obv15']:>6.2f} {c['rs50w'] or 0:>6.2f} {c['ret10']:>5.1f}% "
            f"{c['std20']:>5.2f} {star:>3}"
        )

    lines.append(f"\n=== 【参考】gap<5% + RS50w>1.3 だがOBV>=1.0: {len(near_list)}銘柄 ===")
    lines.append(f"{'Code':6} {'Name':23} {'Price':>8} {'gap%':>5} {'OBV15':>6} {'RS50w':>6} {'ret10':>6}")
    lines.append("-" * 70)
    for c in near_list[:20]:
        lines.append(
            f"{c['code']:6} {c['name']:23} {c['price']:>8,.0f} {c['gap']:>4.1f}% "
            f"{c['obv15']:>6.2f} {c['rs50w'] or 0:>6.2f} {c['ret10']:>5.1f}%"
        )

    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
    print(f"DONE: must={len(must_list)}, near={len(near_list)}")

if __name__ == '__main__':
    main()

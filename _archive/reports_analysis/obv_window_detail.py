"""
OBVウィンドウ詳細分析
- OBV連続値でのHit率カーブ（どの閾値が最適か）
- windowごとのOBV分布
- OBV×gap_sma50 複合効果
- window間の相関（10日/15日/20日は同じ銘柄を選ぶか）
"""
import json, os, sys, time
from collections import defaultdict
import statistics

GH_DIR  = r'C:\Users\yohei\Documents\invest-system-github'
RESULTS = GH_DIR + r'\reports\false_bo_v3_results.json'
OUT_FILE= GH_DIR + r'\reports\obv_window_detail.txt'

sys.path.insert(0, GH_DIR)
import stock_mcp_server as s

def load_bars(code):
    try:
        bars = s._fetch_daily(code, days=2000)
        if not bars: return None, None, None
        dates, closes, vols = [], [], []
        for b in bars:
            c = float(b.get('AdjC') or b.get('C') or 0)
            v = float(b.get('AdjVo') or b.get('Vo') or b.get('V') or 0)
            if c > 0:
                dates.append(b['Date']); closes.append(c); vols.append(v)
        return dates, closes, vols
    except: return None, None, None

def calc_obv(closes, vols, idx, w):
    if idx < w: return None
    cw = closes[idx-w:idx]; vw = vols[idx-w:idx]
    up = sum(vw[i] for i in range(1,len(cw)) if cw[i]>=cw[i-1])
    dn = sum(vw[i] for i in range(1,len(cw)) if cw[i]< cw[i-1])
    return up/dn if dn>0 else 2.0

def hit_rate_at_threshold(records, w_key, threshold):
    """OBV[w] <= threshold の銘柄のHit率"""
    filt = [r for r in records if r[w_key] is not None and r[w_key] <= threshold]
    if not filt: return None, 0
    hits = sum(1 for r in filt if r['hit'])
    return hits/len(filt)*100, len(filt)

def main():
    with open(RESULTS, encoding='utf-8') as f:
        rdata = json.load(f)

    WINDOWS = [5, 10, 15, 20, 30, 40]

    by_code = defaultdict(list)
    for ev in rdata:
        by_code[ev['code']].append(ev)
    codes = list(by_code.keys())

    # 全イベントのOBV値を収集
    records = []  # {'hit':bool, 'gap':float, 'obv_5':..., 'obv_10':..., ...}
    done = 0

    for code in codes:
        events = by_code[code]
        dates, closes, vols = load_bars(code)
        if closes is None: done+=1; continue
        didx = {d:i for i,d in enumerate(dates)}

        for ev in events:
            out = ev.get('outcome','')
            if out not in ('TARGET_HIT','STOP_LOSS'): continue
            ed = ev.get('date','')
            if ed not in didx: continue
            idx = didx[ed]
            hit = (out=='TARGET_HIT')
            gap = ev.get('gap_sma50', None)

            rec = {'hit': hit, 'gap': gap, 'code': code, 'date': ed}
            for w in WINDOWS:
                rec[f'obv_{w}'] = calc_obv(closes, vols, idx, w)
            records.append(rec)
        done+=1
        if done % 50 == 0:
            with open(OUT_FILE,'w',encoding='utf-8') as f:
                f.write(f"Progress {done}/{len(codes)}\n")
        time.sleep(0.03)

    lines = [f"処理完了: {done}銘柄  {len(records)}イベント\n"]

    # ──────────────────────────────────────────────────
    # 1. OBV連続閾値でのHit率カーブ（15日・20日を重点）
    # ──────────────────────────────────────────────────
    lines.append("=" * 60)
    lines.append("① OBV閾値別 Hit率カーブ（n>=10 のみ表示）")
    lines.append("=" * 60)
    thresholds = [0.5, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.7, 2.0, 2.5, 3.0, 99]

    for w in [10, 15, 20]:
        wk = f'obv_{w}'
        lines.append(f"\n--- window={w}日 ---")
        lines.append(f"  {'OBV<=':>8}  {'Hit率':>6}  {'n':>5}  {'累積%':>6}")
        lines.append("  " + "-"*35)
        total_n = len([r for r in records if r[wk] is not None])
        for thr in thresholds:
            rate, n = hit_rate_at_threshold(records, wk, thr)
            if rate is None or n < 10: continue
            cum_pct = n/total_n*100
            thr_str = f"<={thr:.1f}" if thr < 99 else "全体"
            lines.append(f"  {thr_str:>8}  {rate:>5.1f}%  {n:>5}  {cum_pct:>5.1f}%")

    # ──────────────────────────────────────────────────
    # 2. OBV分布（どの範囲に何件あるか）
    # ──────────────────────────────────────────────────
    lines.append("\n" + "=" * 60)
    lines.append("② OBV値の分布（windowごと）")
    lines.append("=" * 60)
    bkt_edges = [0, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 999]
    bkt_names = ['<0.5','0.5-0.8','0.8-1.0','1.0-1.2','1.2-1.5','1.5-2.0','2.0-3.0','>3.0']

    hdr = f"{'範囲':10}" + "".join(f"  {w:>3}日n" for w in WINDOWS)
    lines.append(hdr)
    lines.append("-"*(10+len(WINDOWS)*7))
    for i, bname in enumerate(bkt_names):
        row = f"{bname:10}"
        for w in WINDOWS:
            wk = f'obv_{w}'
            cnt = sum(1 for r in records if r[wk] is not None
                      and bkt_edges[i] <= r[wk] < bkt_edges[i+1])
            row += f"  {cnt:>5}"
        lines.append(row)

    # ──────────────────────────────────────────────────
    # 3. OBV×gap_sma50 複合効果
    # ──────────────────────────────────────────────────
    lines.append("\n" + "=" * 60)
    lines.append("③ OBV×gap_sma50 複合フィルター（window=15日）")
    lines.append("  gap<5% かつ OBV<=X のHit率")
    lines.append("=" * 60)
    wk = 'obv_15'
    gap_filt = [r for r in records if r.get('gap') is not None and r['gap'] < 5 and r[wk] is not None]
    all_filt  = [r for r in records if r[wk] is not None]

    lines.append(f"\n  gap<5%のみ: n={len(gap_filt)}  Hit率={sum(r['hit'] for r in gap_filt)/len(gap_filt)*100:.1f}%" if gap_filt else "")
    lines.append(f"  全体     : n={len(all_filt)}  Hit率={sum(r['hit'] for r in all_filt)/len(all_filt)*100:.1f}%\n")

    lines.append(f"  {'OBV<=':>8}  {'gap<5%Hit%':>11}  {'gap<5%n':>8}  {'全体Hit%':>8}  {'全体n':>6}")
    lines.append("  " + "-"*55)
    for thr in [0.8, 1.0, 1.2, 1.5, 2.0, 99]:
        g_filt = [r for r in gap_filt if r[wk] <= thr]
        a_filt = [r for r in all_filt if r[wk] <= thr]
        if not g_filt or not a_filt: continue
        g_rate = sum(r['hit'] for r in g_filt)/len(g_filt)*100
        a_rate = sum(r['hit'] for r in a_filt)/len(a_filt)*100
        thr_str = f"<={thr:.1f}" if thr < 99 else "全体"
        lines.append(f"  {thr_str:>8}  {g_rate:>10.1f}%  {len(g_filt):>8}  {a_rate:>8.1f}%  {len(a_filt):>6}")

    # ──────────────────────────────────────────────────
    # 4. window間の一致率（10/15/20日は同じ判断をするか）
    # ──────────────────────────────────────────────────
    lines.append("\n" + "=" * 60)
    lines.append("④ window間の一致率（OBV<1.0 vs OBV>=1.0 の判断）")
    lines.append("=" * 60)
    pairs = [(10,15),(10,20),(15,20),(5,15),(20,30)]
    lines.append(f"\n  {'組合せ':10}  {'一致率':>7}  {'両方<1.0':>9}  {'両方>=1.0':>10}  {'不一致':>7}")
    lines.append("  " + "-"*55)
    for w1,w2 in pairs:
        k1,k2 = f'obv_{w1}', f'obv_{w2}'
        both = [r for r in records if r[k1] is not None and r[k2] is not None]
        agree_lo = sum(1 for r in both if r[k1]<1.0 and r[k2]<1.0)
        agree_hi = sum(1 for r in both if r[k1]>=1.0 and r[k2]>=1.0)
        disagree = len(both) - agree_lo - agree_hi
        rate = (agree_lo+agree_hi)/len(both)*100 if both else 0
        lines.append(f"  {w1:>2}日vs{w2:>2}日  {rate:>6.1f}%  {agree_lo:>9}  {agree_hi:>10}  {disagree:>7}")

    # ──────────────────────────────────────────────────
    # 5. OBV<1.0の銘柄の特徴（gap_sma50, rs50w等）
    # ──────────────────────────────────────────────────
    lines.append("\n" + "=" * 60)
    lines.append("⑤ OBV<1.0 vs OBV>=1.5 の銘柄特徴比較（window=15日）")
    lines.append("=" * 60)
    wk = 'obv_15'
    lo_grp = [r for r in records if r[wk] is not None and r[wk] < 1.0]
    hi_grp = [r for r in records if r[wk] is not None and r[wk] >= 1.5]

    for label, grp in [("OBV<1.0", lo_grp), ("OBV>=1.5", hi_grp)]:
        if not grp: continue
        gaps = [r['gap'] for r in grp if r.get('gap') is not None]
        hit_r= sum(r['hit'] for r in grp)/len(grp)*100
        lines.append(f"\n  {label}  n={len(grp)}  Hit率={hit_r:.1f}%")
        if gaps:
            lines.append(f"    gap_sma50: 中央値={statistics.median(gaps):.1f}%  平均={statistics.mean(gaps):.1f}%  <5%の割合={sum(1 for g in gaps if g<5)/len(gaps)*100:.1f}%")

    with open(OUT_FILE,'w',encoding='utf-8') as f:
        f.write("\n".join(lines))
    print(f"DONE: {len(records)} events")

if __name__=='__main__':
    main()

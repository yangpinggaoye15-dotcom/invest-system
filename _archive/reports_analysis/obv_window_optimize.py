"""
OBVウィンドウ最適化: 5/10/15/20/30/40日 で Hit率を比較
"""
import json, os, sys, time
from collections import defaultdict

GH_DIR  = r'C:\Users\yohei\Documents\invest-system-github'
RESULTS = GH_DIR + r'\reports\false_bo_v3_results.json'
OUT_FILE= GH_DIR + r'\reports\obv_window_result.txt'

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
    except Exception:
        return None, None, None

def calc_obv(closes, vols, idx, w):
    if idx < w: return None
    cw = closes[idx-w:idx]; vw = vols[idx-w:idx]
    up = sum(vw[i] for i in range(1,len(cw)) if cw[i]>=cw[i-1])
    dn = sum(vw[i] for i in range(1,len(cw)) if cw[i]< cw[i-1])
    return up/dn if dn>0 else 2.0

def main():
    with open(RESULTS, encoding='utf-8') as f:
        rdata = json.load(f)

    WINDOWS = [5, 10, 15, 20, 30, 40]
    BUCKETS = [('<1.0',   lambda x:x<1.0),
               ('1.0-1.5',lambda x:1.0<=x<1.5),
               ('1.5-2.0',lambda x:1.5<=x<2.0),
               ('>2.0',   lambda x:x>=2.0)]

    stats  = {w:{b[0]:{'h':0,'s':0} for b in BUCKETS} for w in WINDOWS}
    totals = {w:{'h':0,'s':0} for w in WINDOWS}

    by_code = defaultdict(list)
    for ev in rdata:
        by_code[ev['code']].append(ev)
    codes = list(by_code.keys())
    done = skip = matched = 0

    for code in codes:
        events = by_code[code]
        dates, closes, vols = load_bars(code)
        if closes is None:
            skip += 1; done += 1; continue
        didx = {d:i for i,d in enumerate(dates)}

        for ev in events:
            out = ev.get('outcome','')
            if out not in ('TARGET_HIT','STOP_LOSS'): continue
            ed = ev.get('date','')
            if ed not in didx: continue
            idx = didx[ed]
            hit = (out=='TARGET_HIT')
            matched += 1

            for w in WINDOWS:
                obv = calc_obv(closes, vols, idx, w)
                if obv is None: continue
                if hit: totals[w]['h']+=1
                else:   totals[w]['s']+=1
                for bn,bf in BUCKETS:
                    if bf(obv):
                        if hit: stats[w][bn]['h']+=1
                        else:   stats[w][bn]['s']+=1
                        break
        done += 1
        if done % 50 == 0:
            msg = f"Progress {done}/{len(codes)} (matched={matched})\n"
            with open(OUT_FILE,'w',encoding='utf-8') as f:
                f.write(msg)
        time.sleep(0.03)

    lines = [f"処理完了: {done}/{len(codes)} 銘柄  skip={skip}  matched_events={matched}\n"]

    lines.append("=== 全体Hit率（windowごと） ===")
    lines.append(f"{'Window':>8}  {'Hit率':>6}  {'n':>5}")
    lines.append("-"*28)
    for w in WINDOWS:
        t=totals[w]; n=t['h']+t['s']
        lines.append(f"{w:>6}日  {t['h']/n*100:>5.1f}%  {n:>5}" if n>0 else f"{w:>6}日  {'N/A':>5}  {n:>5}")

    lines.append("\n=== OBVバケツ別 Hit率（windowごと） ===")
    lines.append(f"{'OBV範囲':12}" + "".join(f"  {w:>2}日Hit%" for w in WINDOWS))
    lines.append("-"*(12+len(WINDOWS)*10))
    for bn,_ in BUCKETS:
        row = f"{bn:12}"
        for w in WINDOWS:
            sv=stats[w][bn]; n=sv['h']+sv['s']
            row += f"  {sv['h']/n*100:>6.1f}%" if n>=3 else f"  {'N/A':>6}"
        lines.append(row)

    lines.append("\n=== n（サンプル数）===")
    lines.append(f"{'OBV範囲':12}" + "".join(f"  {w:>4}日n" for w in WINDOWS))
    lines.append("-"*(12+len(WINDOWS)*8))
    for bn,_ in BUCKETS:
        row = f"{bn:12}"
        for w in WINDOWS:
            sv=stats[w][bn]; row += f"  {sv['h']+sv['s']:>5}"
        lines.append(row)

    lines.append("\n=== 最重要: OBV低(<1.0) vs OBV高(>1.5) のHit率差 ===")
    lines.append(f"{'Window':>8}  {'OBV<1.0':>8}  {'OBV>1.5':>8}  {'差(低-高)':>8}")
    lines.append("-"*45)
    for w in WINDOWS:
        lo=stats[w]['<1.0']
        h15=stats[w]['1.5-2.0']; h20=stats[w]['>2.0']
        hi_n=h15['h']+h15['s']+h20['h']+h20['s']; hi_h=h15['h']+h20['h']
        lo_n=lo['h']+lo['s']
        lo_r=lo['h']/lo_n*100 if lo_n>0 else 0
        hi_r=hi_h/hi_n*100   if hi_n>0 else 0
        lines.append(f"{w:>6}日  {lo_r:>7.1f}%  {hi_r:>7.1f}%  {lo_r-hi_r:>+7.1f}%")
    lines.append("\n[解釈] 差が大きいほどそのwindowでOBVの予測力が高い")

    with open(OUT_FILE,'w',encoding='utf-8') as f:
        f.write("\n".join(lines))
    print(f"DONE: {done} stocks, {matched} events")

if __name__=='__main__':
    main()

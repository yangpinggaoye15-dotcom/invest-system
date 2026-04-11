"""
最終エントリーフィルター v3 - SQLiteのみで高速スクリーニング（API不要）
必須: 7/7 + gap_sma50 0〜5% + OBV(15日)<1.0 + RS50w>1.3
加点: std<2.0 + 前10日<+5%

環境変数:
  INVEST_BASE_DIR   : データDB/JSONのルート（デフォルト: ./）
  INVEST_GITHUB_DIR : スクリプト・出力のルート（デフォルト: ./）
"""
import sqlite3, json, os, statistics
from datetime import datetime

BASE_DIR = os.environ.get('INVEST_BASE_DIR', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GH_DIR   = os.environ.get('INVEST_GITHUB_DIR', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH  = os.path.join(BASE_DIR, 'data', 'stock_prices.db')
SF_JSON  = os.path.join(BASE_DIR, 'data', 'screen_full_results.json')
OUT_TXT  = os.path.join(GH_DIR,  'reports', 'entry_screen_result.txt')
OUT_JSON = os.path.join(GH_DIR,  'reports', 'entry_screen_result.json')

def calc_metrics(conn, code):
    rows = conn.execute(
        'SELECT date, close, volume FROM daily_prices '
        'WHERE code=? AND close IS NOT NULL ORDER BY date',
        (code,)
    ).fetchall()

    if len(rows) < 55:
        return None

    closes = [r[1] for r in rows]
    vols   = [r[2] or 0 for r in rows]
    price  = closes[-1]
    latest_date = rows[-1][0]

    # SMA50
    sma50 = sum(closes[-50:]) / 50
    gap   = (price - sma50) / sma50 * 100

    # RS50w (250日前比)
    rs50w = price / closes[-251] if len(closes) >= 251 and closes[-251] > 0 else None

    # OBV15日（直前15日の上昇/下落出来高比）
    cw = closes[-16:-1]
    vw = vols[-16:-1]
    up = sum(vw[i] for i in range(1, len(cw)) if cw[i] >= cw[i-1])
    dn = sum(vw[i] for i in range(1, len(cw)) if cw[i] <  cw[i-1])
    obv15 = up / dn if dn > 0 else 2.0

    # 前10日変化率
    ret10 = (price - closes[-11]) / closes[-11] * 100 if len(closes) >= 11 and closes[-11] > 0 else 0

    # 日次std（直前20日）
    cw20 = closes[-21:-1]
    rets = [(cw20[i]-cw20[i-1])/cw20[i-1]*100 for i in range(1, len(cw20)) if cw20[i-1] > 0]
    std20 = statistics.stdev(rets) if len(rets) > 1 else 99

    return {
        'price': price,
        'sma50': round(sma50, 1),
        'gap':   round(gap, 1),
        'rs50w': round(rs50w, 2) if rs50w else None,
        'obv15': round(obv15, 2),
        'ret10': round(ret10, 1),
        'std20': round(std20, 2),
        'latest_date': latest_date,
    }

def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: DB not found: {DB_PATH}")
        return
    if not os.path.exists(SF_JSON):
        print(f"ERROR: screen_full_results.json not found: {SF_JSON}")
        return

    conn = sqlite3.connect(DB_PATH)

    with open(SF_JSON, encoding='utf-8') as f:
        sf = json.load(f)

    passed = [(v['code'], v['name'][:28]) for v in sf.values()
              if isinstance(v, dict) and v.get('passed')]
    print(f"7/7 PASS: {len(passed)}銘柄 → エントリーフィルター適用中...")

    candidates = []
    skip = 0

    for code, name in passed:
        m = calc_metrics(conn, code)
        if m is None:
            skip += 1
            continue

        f_gap  = 0 <= m['gap'] < 5.0
        f_obv  = m['obv15'] < 1.0
        f_rs   = (m['rs50w'] or 0) > 1.3
        f_std  = m['std20'] < 2.0
        f_ret  = m['ret10'] < 5.0
        bonus  = sum([f_std, f_ret])

        must = f_gap and f_obv and f_rs
        # SMA50直下3%以内：押し目候補
        near = (not f_gap and -3.0 <= m['gap'] < 0 and f_obv and f_rs)

        rec = {
            'code': code, 'name': name,
            'category': 'must' if must else ('near' if near else 'other'),
            'bonus': bonus,
            'f_gap': f_gap, 'f_obv': f_obv, 'f_rs': f_rs,
            'f_std': f_std, 'f_ret': f_ret,
            **m
        }
        if must or near:
            candidates.append(rec)

    conn.close()

    run_date = candidates[0]['latest_date'] if candidates else datetime.now().strftime('%Y-%m-%d')
    must_list = sorted([c for c in candidates if c['category']=='must'],
                       key=lambda x: (-x['bonus'], x['obv15']))
    near_list = sorted([c for c in candidates if c['category']=='near'],
                       key=lambda x: x['obv15'])

    # ── テキスト出力 ────────────────────────────────────────
    lines = [
        f"エントリースクリーニング結果  {run_date}",
        f"処理: {len(passed)}銘柄  skip={skip}",
        f"フィルター: 7/7 + gap 0〜5% + OBV15日<1.0 + RS50w>1.3",
        ""
    ]
    lines += [
        f"{'='*72}",
        f"① 全条件クリア: {len(must_list)}銘柄  (★★=std<2.0かつ前10日<5%)",
        f"{'='*72}",
        f"{'Code':6} {'Name':29} {'Price':>8} {'gap%':>5} {'OBV15':>6} {'RS50w':>6} {'ret10':>6} {'std':>5} ★",
        "-"*82,
    ]
    for c in must_list:
        star = "★★" if c['bonus']==2 else "★ " if c['bonus']==1 else "  "
        lines.append(
            f"{c['code']:6} {c['name']:29} {c['price']:>8,.0f} {c['gap']:>+4.1f}% "
            f"{c['obv15']:>6.2f} {c['rs50w'] or 0:>6.2f} {c['ret10']:>+5.1f}% "
            f"{c['std20']:>5.2f} {star}"
        )

    lines += [
        f"",
        f"{'='*72}",
        f"② SMA50直下 -3〜0% 押し目候補: {len(near_list)}銘柄",
        f"{'='*72}",
        f"{'Code':6} {'Name':29} {'Price':>8} {'gap%':>5} {'OBV15':>6} {'RS50w':>6} {'ret10':>6}",
        "-"*72,
    ]
    for c in near_list:
        lines.append(
            f"{c['code']:6} {c['name']:29} {c['price']:>8,.0f} {c['gap']:>+4.1f}% "
            f"{c['obv15']:>6.2f} {c['rs50w'] or 0:>6.2f} {c['ret10']:>+5.1f}%"
        )

    os.makedirs(os.path.dirname(OUT_TXT), exist_ok=True)
    with open(OUT_TXT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    # ── JSON出力（サイト表示用）──────────────────────────────
    def to_json_rec(c):
        return {
            'code':    c['code'],
            'name':    c['name'],
            'price':   c['price'],
            'gap':     c['gap'],
            'obv15':   c['obv15'],
            'rs50w':   c['rs50w'],
            'ret10':   c['ret10'],
            'std20':   c['std20'],
            'bonus':   c['bonus'],
        }

    result_json = {
        'generated': run_date,
        'filter': 'gap 0-5% + OBV15<1.0 + RS50w>1.3 + 7/7',
        'must':   [to_json_rec(c) for c in must_list],
        'near':   [to_json_rec(c) for c in near_list],
    }
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)

    print(f"完了: must={len(must_list)}銘柄, near={len(near_list)}銘柄")
    print(f"  → {OUT_TXT}")
    print(f"  → {OUT_JSON}")

if __name__ == '__main__':
    main()

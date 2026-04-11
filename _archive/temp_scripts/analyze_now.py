#!/usr/bin/env python3
"""Minervini screening analysis"""
import json, os, sys
from datetime import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with open("data/screen_full_results.json") as f:
    d = json.load(f)

items = list(d.values()) if isinstance(d, dict) else d

def get_score(x):
    s = x.get("score", 0)
    if isinstance(s, str) and "/" in s:
        return int(s.split("/")[0])
    return int(s) if s else 0

def get_rs50(x):
    v = x.get("rs50w") or x.get("rs_50w") or 0
    return float(v) if v else 0.0

passed = [x for x in items if x.get("passed")]
s7 = [x for x in passed if get_score(x) == 7]
s6 = [x for x in passed if get_score(x) == 6]
s5 = [x for x in passed if get_score(x) == 5]

print(f"=== Minervini スクリーニング {datetime.now().strftime('%Y-%m-%d')} ===")
print(f"全銘柄: {len(items)}  通過: {len(passed)}  スコア7: {len(s7)}  6: {len(s6)}  5: {len(s5)}")
print()

def fmt_row(x):
    code  = x.get("code", "")
    name  = x.get("name", "")[:14]
    rs50  = get_rs50(x)
    rs30  = float(x.get("rs30w") or 0)
    rs10  = float(x.get("rs10w") or 0)
    price = float(x.get("price") or 0)
    h52   = float(x.get("high52") or 0)
    near  = (price / h52 * 100) if h52 else 0
    sc    = get_score(x)
    return f"  {code} {name:<14} sc={sc} RS50={rs50:.3f} RS30={rs30:.3f} RS10={rs10:.3f}  {price:>8,.0f}円  52wH{near:.0f}%"

print("--- Score 7 (RS50w降順) ---")
for x in sorted(s7, key=lambda x: -get_rs50(x)):
    print(fmt_row(x))

print()
print("--- Score 6 (RS50w降順, 上位20) ---")
for x in sorted(s6, key=lambda x: -get_rs50(x))[:20]:
    print(fmt_row(x))

print()
print("--- RS50w 全体トップ10 (スコア問わず) ---")
rs_all = sorted([x for x in items if get_rs50(x) > 0], key=lambda x: -get_rs50(x))[:10]
for x in rs_all:
    print(fmt_row(x))

print()
near_high = [x for x in passed if x.get("high52") and float(x.get("price") or 0) / float(x.get("high52") or 1) >= 0.98]
near_high_s = sorted(near_high, key=lambda x: -get_rs50(x))
print(f"--- 52週高値98%以上 + Minervini通過: {len(near_high)} 銘柄 ---")
for x in near_high_s[:20]:
    print(fmt_row(x))

#!/usr/bin/env python3
"""財務推移を表示"""
import sqlite3, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(BASE, "data", "fins_data.db")

code = sys.argv[1] if len(sys.argv) > 1 else "5803"

con = sqlite3.connect(DB)
rows = con.execute("""
    SELECT fy, period, date, sales, op, np, eps, bps, div, equity_ratio,
           forecast_sales, forecast_np, forecast_eps
    FROM fins
    WHERE code = ?
    ORDER BY date DESC
    LIMIT 20
""", (code,)).fetchall()
con.close()

if not rows:
    print(f"No fins data for {code}")
    sys.exit(1)

cols = ["FY","period","date","売上(億)","営利(億)","純利(億)","EPS","BPS","配当","自己資本%","予想売上","予想純利","予想EPS"]

def fmt(v, div=100_000_000):
    if v is None: return "  N/A"
    if div: return f"{v/div:>8.1f}"
    return f"{v:>8.2f}"

print(f"\n=== {code} 業績推移 ===\n")
print(f"{'FY':<10} {'期間':<6} {'売上(億)':<10} {'営利(億)':<10} {'純利(億)':<10} {'営利率':<7} {'EPS':<8} {'配当':<6} {'自己資%':<8}")
print("-" * 85)

prev_sales = None
for r in reversed(rows):
    fy, period, date, sales, op, np_, eps, bps, div, eq, fs, fn, fe = r
    op_margin = f"{op/sales*100:.1f}%" if sales and op else "  N/A"
    sales_str  = fmt(sales)
    op_str     = fmt(op)
    np_str     = fmt(np_)
    eps_str    = f"{eps:>8.1f}" if eps else "     N/A"
    div_str    = f"{div:>6.1f}" if div else "   N/A"
    eq_str     = f"{eq:>7.1f}%" if eq else "    N/A"

    # YoY
    yoy = ""
    if prev_sales and sales:
        chg = (sales - prev_sales) / abs(prev_sales) * 100
        yoy = f"({chg:+.1f}%)" if abs(chg) < 999 else ""
    prev_sales = sales

    print(f"{fy:<10} {period:<6} {sales_str} {op_str} {np_str} {op_margin:<7} {eps_str} {div_str} {eq_str}  {yoy}")

# 最新の予想
latest = rows[0]
fs, fn, fe = latest[10], latest[11], latest[12]
if any(x for x in [fs, fn, fe]):
    print()
    print("── 直近予想 ──")
    if fs: print(f"  予想売上  : {fs/1e8:.0f}億円")
    if fn: print(f"  予想純利益: {fn/1e8:.0f}億円")
    if fe: print(f"  予想EPS   : {fe:.1f}円")

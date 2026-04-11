import sqlite3, sys
from pathlib import Path

db = Path(__file__).parent / "stock_prices.db"
con = sqlite3.connect(db)

tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
tname = tables[0][0]
cols = [c[1] for c in con.execute(f"PRAGMA table_info({tname})").fetchall()]
sys.stdout.write(f"Table={tname} Cols={cols}\n")

dates = con.execute(f"SELECT DISTINCT date FROM {tname} ORDER BY date DESC LIMIT 5").fetchall()
sys.stdout.write(f"Latest dates: {[d[0] for d in dates]}\n")

query = f"""
WITH ytd_high AS (
    SELECT code, MAX(high) as ytd_max
    FROM {tname}
    WHERE date >= '2026-01-01' AND date <= '2026-04-03'
    GROUP BY code
),
apr3 AS (
    SELECT code, high, close, volume
    FROM {tname}
    WHERE date = '2026-04-03'
)
SELECT a.code, a.high, a.close, y.ytd_max
FROM apr3 a
JOIN ytd_high y ON a.code = y.code
WHERE a.high >= y.ytd_max * 0.999
ORDER BY a.high / y.ytd_max DESC
"""
rows = con.execute(query).fetchall()
con.close()
sys.stdout.write(f"\n4/3年初来高値更新: {len(rows)}銘柄\n")
for r in rows:
    sys.stdout.write(f"  {r[0]}  high={r[1]:.0f}  close={r[2]:.0f}\n")
sys.stdout.flush()

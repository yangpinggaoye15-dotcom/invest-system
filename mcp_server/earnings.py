"""業績品質チェック (Team 4 統合分析用)。

cranky-nash ブランチから 2026-04-18 に移植。

- `_calc_earnings_score(code_4)`: 4 基準で業績品質を評価し S/A/B/C/D グレード付与
  - ① 年次安定性: 直近 3-5 年 OP 成長が 60% 以上の期で ≥5%
  - ② 直近通期 OP 成長: 前期 YoY ≥10%
  - ③ 四半期 YoY 成長: 直近 2-3Q OP≥20% + 売上≥10%
  - ④ 利益率トレンド: 売上高営業利益率が前年比改善
- `check_earnings(code)`: MCP tool として 4 基準の結果を表形式で返す
"""
from __future__ import annotations

from mcp_server._context import mcp
from mcp_server._fins_fetch import _fetch_fins_history
from mcp_server.equity import _lookup_name


def _calc_earnings_score(code_4: str) -> dict:
    """
    ミネルヴィニ流業績チェック（4基準）
    収益性・持続性・確実性を数値化する。

    チェック項目:
      ① 年次安定性    : 直近3-5期のOP成長が≥5%を60%以上の期で達成
      ② 直近通期OP成長: 最新FYのYoY OP成長 ≥10%（理想30%+）
      ③ 四半期YoY成長 : 直近2-3Qの前年同期比 OP≥20%・売上≥10%
      ④ 利益率トレンド: 通期の売上高営業利益率が前年比で改善

    Returns:
        dict with score(0-4), grade(S/A/B/C/D), checks, fy_trend, quarterly, notes
    """
    history = _fetch_fins_history(code_4)
    if not history:
        return {"error": "no financial data"}

    # FY（通期）レコード — sales/op 両方必要 / 同一FYは最新開示を採用
    _fy_raw = [r for r in history
               if r.get("period") == "FY"
               and r.get("op") is not None
               and r.get("sales") is not None]
    # 同じFY年度(fy key)に複数レコード（修正開示等）がある場合、開示日最新を選ぶ
    _fy_dedup: dict = {}
    for r in _fy_raw:
        fy_key = r.get("fy", "")
        if fy_key not in _fy_dedup or r.get("date", "") > _fy_dedup[fy_key].get("date", ""):
            _fy_dedup[fy_key] = r
    fy_records = sorted(_fy_dedup.values(), key=lambda x: x.get("fy", ""))
    # 四半期累計レコード（1Q=Q1, 2Q=H1, 3Q=9ヶ月）
    q_records = sorted(
        [r for r in history
         if r.get("period") in ("1Q", "2Q", "3Q")
         and r.get("op") is not None],
        key=lambda x: (
            x.get("fy", ""),
            {"1Q": 1, "2Q": 2, "3Q": 3}.get(x.get("period", ""), 0)
        )
    )

    # ── FY期ラベル変換ヘルパー（"2026-03" → "26/3期"） ──────────
    def _fy_label(fy: str) -> str:
        """J-Quants FY end string → 短縮表示 ("2026-03" → "26/3期")
        日本企業の慣例: 期末年月をそのまま表記 ("2026年3月期" → "26/3期")
        """
        try:
            y = int(fy[:4])
            m = int(fy[5:7]) if len(fy) >= 7 else 3
            return f"{str(y)[2:]}/{m:02d}期"  # "2026-03" → "26/3期"
        except Exception:
            return fy

    # 四半期累計の期間説明（"2026-03" + "3Q" → "Apr-Dec'25"）
    def _q_period_str(fy: str, period: str) -> str:
        try:
            y = int(fy[:4])
            m = int(fy[5:7]) if len(fy) >= 7 else 3
            # FY start: if 3月期, FY starts April of y-1
            start_y = y - 1 if m == 3 else y
            months = {"1Q": f"4-6月'{str(start_y)[2:]}",
                      "2Q": f"4-9月'{str(start_y)[2:]}",
                      "3Q": f"4-12月'{str(start_y)[2:]}",
                      "FY": f"通期'{str(start_y)[2:]}"}
            return months.get(period, period)
        except Exception:
            return period

    checks = []
    score  = 0

    # ── ① 年次安定性（3-5年 OP推移） ──────────────────────────
    annual_growths = []   # テーブル表示用に期間ラベルも保持
    if len(fy_records) >= 3:
        recent = fy_records[-5:]
        for i in range(1, len(recent)):
            p, c = recent[i-1], recent[i]
            p_op, c_op = p["op"], c["op"]
            if p_op and p_op > 0:
                g     = (c_op / p_op - 1) * 100
                s_g   = ((c["sales"] / p["sales"] - 1) * 100
                         if p.get("sales") and p["sales"] > 0 and c.get("sales")
                         else None)
                annual_growths.append({
                    "from_fy":    p["fy"],
                    "to_fy":      c["fy"],
                    "from_label": _fy_label(p["fy"]),
                    "to_label":   _fy_label(c["fy"]),
                    "op_prev":    p_op,
                    "op_curr":    c_op,
                    "op_growth":  round(g, 1),
                    "sales_growth": round(s_g, 1) if s_g is not None else None,
                    "passed":     g >= 5,
                })
        passed_n = sum(1 for r in annual_growths if r["passed"])
        stable   = len(annual_growths) > 0 and passed_n / len(annual_growths) >= 0.6
        checks.append({
            "name":         "① 年次安定性（3-5年）",
            "passed":       stable,
            "threshold":    "OP成長≥5%を60%以上の期で達成",
            "annual_rows":  annual_growths,
        })
        if stable:
            score += 1
    else:
        checks.append({
            "name": "① 年次安定性", "passed": None,
            "threshold": "OP成長≥5%を60%以上の期で達成",
            "detail": f"データ不足（FY {len(fy_records)}期 / 3期以上必要）"
        })

    # ── ② 直近通期OP成長（1-2年） ─────────────────────────────
    recent_fy_data = None
    if len(fy_records) >= 2:
        lat, prv = fy_records[-1], fy_records[-2]
        if prv["op"] and prv["op"] > 0:
            op_g  = (lat["op"] / prv["op"] - 1) * 100
            s_g   = ((lat["sales"] / prv["sales"] - 1) * 100
                     if prv.get("sales") and prv["sales"] > 0 and lat.get("sales")
                     else None)
            passed = op_g >= 10
            grade_str = ("◎30%+" if op_g >= 30 else
                         "○20%+" if op_g >= 20 else
                         "△10%+" if op_g >= 10 else "✗10%未満")
            recent_fy_data = {
                "from_label":  _fy_label(prv["fy"]),
                "to_label":    _fy_label(lat["fy"]),
                "op_prev":     prv["op"],
                "op_curr":     lat["op"],
                "sales_prev":  prv.get("sales"),
                "sales_curr":  lat.get("sales"),
                "op_growth":   round(op_g, 1),
                "sales_growth": round(s_g, 1) if s_g is not None else None,
                "grade_str":   grade_str,
            }
            checks.append({
                "name":          "② 直近通期OP成長",
                "passed":        passed,
                "threshold":     "≥10%（理想30%+）",
                "op_growth":     round(op_g, 1),
                "recent_fy":     recent_fy_data,
            })
            if passed:
                score += 1
        else:
            checks.append({"name": "② 直近通期OP成長", "passed": None,
                            "threshold": "≥10%（理想30%+）",
                            "detail": "前年比較不可（前期OP≤0）"})
    else:
        checks.append({"name": "② 直近通期OP成長", "passed": None,
                        "threshold": "≥10%（理想30%+）",
                        "detail": "前年比較データなし"})

    # ── ③ 四半期YoY成長（直近2-3Q） ──────────────────────────
    q_map  = {(r["fy"], r["period"]): r for r in q_records}
    q_chks = []
    seen   = set()
    for r in reversed(q_records):
        key = (r["fy"], r["period"])
        if key in seen:
            continue
        seen.add(key)
        prev_fy  = f"{int(r['fy'][:4]) - 1}{r['fy'][4:]}"
        prev_key = (prev_fy, r["period"])
        if prev_key in q_map:
            p = q_map[prev_key]
            if p["op"] and p["op"] > 0 and r.get("op") is not None:
                op_yoy = (r["op"] / p["op"] - 1) * 100
                s_yoy  = ((r["sales"] / p["sales"] - 1) * 100
                          if r.get("sales") and p.get("sales") and p["sales"] > 0
                          else None)
                q_chks.append({
                    "curr_fy":      r["fy"],
                    "prev_fy":      prev_fy,
                    "period":       r["period"],
                    "curr_label":   _fy_label(r["fy"]),
                    "prev_label":   _fy_label(prev_fy),
                    "period_range": _q_period_str(r["fy"], r["period"]),
                    "op_curr":      r["op"],
                    "op_prev":      p["op"],
                    "sales_curr":   r.get("sales"),
                    "sales_prev":   p.get("sales"),
                    "op_yoy":       round(op_yoy, 1),
                    "sales_yoy":    round(s_yoy, 1) if s_yoy is not None else None,
                    "op_passed":    op_yoy >= 20,
                    "sales_passed": (s_yoy >= 10) if s_yoy is not None else None,
                })
        if len(q_chks) >= 3:
            break

    if q_chks:
        passed_n = sum(1 for q in q_chks if q["op_passed"])
        all_pass = passed_n >= max(1, len(q_chks) - 1)
        checks.append({
            "name":      "③ 四半期YoY成長（直近2-3Q）",
            "passed":    all_pass,
            "threshold": "OP≥20% / 売上≥10%（最大1Q不合格を許容）",
            "q_results": q_chks,
        })
        if all_pass:
            score += 1
    else:
        checks.append({"name": "③ 四半期YoY成長", "passed": None,
                        "threshold": "OP≥20% / 売上≥10%",
                        "detail": "四半期データなし（前年との比較不可）"})

    # ── ④ 売上高営業利益率トレンド ────────────────────────────
    margin_rows = [
        {
            "fy":     r["fy"],
            "label":  _fy_label(r["fy"]),
            "op":     r["op"],
            "sales":  r.get("sales"),
            "margin": round(r["op"] / r["sales"] * 100, 1),
        }
        for r in fy_records[-6:]
        if r.get("op") is not None and r.get("sales") and r["sales"] > 0
    ]
    if len(margin_rows) >= 2:
        delta     = margin_rows[-1]["margin"] - margin_rows[-2]["margin"]
        improving = delta > 0
        trend_str = "↑改善" if delta > 0.5 else ("→横ばい" if abs(delta) <= 0.5 else "↓悪化")
        # 各行に前年差を付加
        for i, row in enumerate(margin_rows):
            row["delta"] = round(row["margin"] - margin_rows[i-1]["margin"], 1) if i > 0 else None
        checks.append({
            "name":          "④ 営業利益率トレンド",
            "passed":        improving,
            "threshold":     "直近期が前年比で改善",
            "trend_str":     trend_str,
            "latest_margin": margin_rows[-1]["margin"],
            "margin_rows":   margin_rows,
        })
        if improving:
            score += 1
    else:
        checks.append({"name": "④ 営業利益率トレンド", "passed": None,
                        "threshold": "直近期が前年比で改善",
                        "detail": "通期データ不足"})

    # ── 総合グレード ──────────────────────────────────────────
    grade = {4: "S", 3: "A", 2: "B", 1: "C", 0: "D"}.get(score, "D")

    # 補足メモ（持続性・確実性）
    notes = []
    if len(fy_records) >= 2:
        lat_op = fy_records[-1].get("op") or 0
        prv_op = fy_records[-2].get("op") or 0
        if prv_op > 0 and lat_op / prv_op > 2.0:
            notes.append("⚠️ 急成長（2倍超）: 持続性・一過性リスクを別途確認")
    if q_chks and q_chks[0]["op_yoy"] < 10:
        notes.append("⚠️ 直近四半期の成長鈍化 — モメンタム失速に注意")
    if margin_rows and margin_rows[-1]["margin"] < 10:
        notes.append("ℹ️ 利益率10%未満 — 製造業・卸売系では許容範囲の場合あり")

    return {
        "score":          score,
        "grade":          grade,
        "checks":         checks,
        "annual_growths": annual_growths,
        "recent_fy":      recent_fy_data,
        "quarterly":      q_chks,
        "margin_rows":    margin_rows,
        "notes":          notes,
    }




@mcp.tool()
def check_earnings(code: str) -> str:
    """
    ミネルヴィニ流業績品質チェック（4基準）を実行する。
    収益性・持続性・確実性をスコアリングしグレード(S/A/B/C/D)で評価。
    各チェックは「いつからいつの数値か」が一目でわかるテーブル形式で出力。

    判定基準:
      ① 年次安定性    : 直近3-5年でOP≥5%成長を60%以上の期で達成
      ② 直近通期OP成長: FY YoY ≥10%（理想30%+）
      ③ 四半期YoY成長 : 直近2-3QのOP≥20% / 売上≥10%（前年同期比）
      ④ 利益率改善    : 通期の売上高営業利益率が前年比で上昇

    Grade: S(4/4)=積極検討 / A(3/4)=検討可 / B(2/4)=慎重 / C(1/4)=要注意 / D(0/4)=スキップ

    Example: check_earnings("6758")
    """
    name   = _lookup_name(code)
    result = _calc_earnings_score(code)
    if "error" in result:
        return f"[{code}] {name}  業績データ取得不可: {result['error']}"

    grade       = result["grade"]
    score       = result["score"]
    grade_emoji = {"S": "🏆", "A": "⭐", "B": "✅", "C": "⚠️", "D": "❌"}.get(grade, "")

    def _ok(passed):
        return "✓" if passed else ("✗" if passed is not None else "?")

    def _bil(v):
        """百万円 → 億円表示"""
        if v is None: return "N/A"
        return f"{v/1e8:.1f}億"

    def _pct(v, sign=True):
        if v is None: return "N/A"
        return f"{v:+.1f}%" if sign else f"{v:.1f}%"

    lines = [
        f"[{code}] {name}",
        f"業績品質スコア: {score}/4  Grade: {grade} {grade_emoji}",
        "=" * 62,
    ]

    for ck in result["checks"]:
        passed = ck.get("passed")
        mk     = _ok(passed)
        result_str = "合格" if passed else ("不合格" if passed is not None else "データなし")
        lines.append(f"\n{mk} {ck['name']}  [{result_str}]  基準: {ck.get('threshold','')}")

        # ① 年次安定性 → 通期OP成長テーブル
        if ck.get("annual_rows"):
            rows = ck["annual_rows"]
            lines.append(f"  {'期間':<20}  {'前期OP':>10}  {'当期OP':>10}  {'OP成長率':>9}  {'売上成長':>9}  {'判定':>4}")
            lines.append(f"  {'-'*68}")
            for r in rows:
                period_str = f"{r['from_label']}→{r['to_label']}"
                s_g_str    = _pct(r.get("sales_growth")) if r.get("sales_growth") is not None else "  N/A"
                lines.append(
                    f"  {period_str:<20}  {_bil(r['op_prev']):>10}  {_bil(r['op_curr']):>10}"
                    f"  {_pct(r['op_growth']):>9}  {s_g_str:>9}  {'✓' if r['passed'] else '✗':>4}"
                )
            passed_n = sum(1 for r in rows if r["passed"])
            lines.append(f"  → {len(rows)}期中 {passed_n}期 合格"
                         f"（合格率 {passed_n/len(rows)*100:.0f}% / 基準60%）")

        # ② 直近通期OP成長 → 前期vs当期テーブル
        elif ck.get("recent_fy"):
            r = ck["recent_fy"]
            lines.append(f"  {'':22}  {'前期':>12}  {'当期':>12}  {'YoY':>9}")
            lines.append(f"  {'-'*62}")
            lines.append(f"  {'期間':<22}  {r['from_label']:>12}  {r['to_label']:>12}  {'':>9}")
            lines.append(
                f"  {'営業利益':<22}  {_bil(r['op_prev']):>12}  {_bil(r['op_curr']):>12}"
                f"  {_pct(r['op_growth']):>9}  {r['grade_str']}"
            )
            if r.get("sales_prev") and r.get("sales_curr"):
                lines.append(
                    f"  {'売上高':<22}  {_bil(r['sales_prev']):>12}  {_bil(r['sales_curr']):>12}"
                    f"  {_pct(r.get('sales_growth')):>9}"
                )

        # ③ 四半期YoY成長 → 前年同期比テーブル
        elif ck.get("q_results"):
            lines.append(
                f"  {'累計期間':^20}  {'前年同期OP':>10}  {'当期OP':>10}  {'OP成長':>8}"
                f"  {'売上成長':>8}  {'判定':>4}"
            )
            lines.append(f"  {'-'*68}")
            for q in ck["q_results"]:
                period_str = f"{q['curr_label']} {q['period']} ({q['period_range']})"
                s_yoy_str  = _pct(q.get("sales_yoy")) if q.get("sales_yoy") is not None else "  N/A"
                lines.append(
                    f"  {period_str:<20}  {_bil(q['op_prev']):>10}  {_bil(q['op_curr']):>10}"
                    f"  {_pct(q['op_yoy']):>8}  {s_yoy_str:>8}  {'✓' if q['op_passed'] else '✗':>4}"
                )
            lines.append(f"  ※ 累計値（期首から各四半期末まで）の前年同期比")

        # ④ 営業利益率トレンド → 年度別テーブル
        elif ck.get("margin_rows"):
            rows = ck["margin_rows"]
            trend = ck.get("trend_str", "")
            lines.append(f"  {'期':^10}  {'売上高':>10}  {'営業利益':>10}  {'利益率':>7}  {'前年差':>7}")
            lines.append(f"  {'-'*54}")
            for r in rows:
                d_str = f"{_pct(r.get('delta'))}" if r.get("delta") is not None else "   —"
                lines.append(
                    f"  {r['label']:^10}  {_bil(r.get('sales')):>10}  {_bil(r['op']):>10}"
                    f"  {_pct(r['margin'], sign=False):>7}  {d_str:>7}"
                )
            lines.append(f"  → トレンド: {trend}（直近: {rows[-1]['margin']:.1f}%）")

        # フォールバック（データなし等）
        elif ck.get("detail"):
            lines.append(f"  {ck['detail']}")

    # 注意事項
    if result.get("notes"):
        lines.append("\n【注意事項】")
        for note in result["notes"]:
            lines.append(f"  {note}")

    # 判断ガイド
    lines += [
        "\n" + "=" * 62,
        "グレード: S(4)=積極検討 / A(3)=検討可 / B(2)=慎重 / C(1)=要注意 / D(0)=スキップ",
        "観  点 : 収益性(②④) / 持続性(①③) / 確実性(決算説明資料・有報で裏付け)",
    ]

    return "\n".join(lines)

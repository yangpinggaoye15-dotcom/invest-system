"""スモークテスト: 主要な純粋関数が動作するかを確認。

リファクタ前後で以下が変わらないことを確認する：
- モジュールがインポートできる
- 基礎ユーティリティ関数（_score_num, _rs26w, screen_to_list）が期待通り動く
- detect_phase がフェーズ判定を返す
- _minervini がミネルヴィニスコアを返す
- 実データ (screen_full_results.json) が整合的

使い方:
    python tests/smoke_test.py

全合格なら exit code 0、1 件でも失敗なら 1。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Windows (cp932) でも emoji を出せるよう stdout を UTF-8 に
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

# ── 環境変数ダミー値（インポート時の KeyError 防止） ─────────
for k in ("ANTHROPIC_API_KEY", "GEMINI_API", "JQUANTS_API_KEY"):
    os.environ.setdefault(k, "dummy")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── テスト集計 ──────────────────────────────────────────────
_PASS = 0
_FAIL = 0
_ERRORS: list[str] = []


def test(name: str, condition: bool, details: str = "") -> None:
    global _PASS, _FAIL
    if condition:
        print(f"  ✅ {name}")
        _PASS += 1
    else:
        suffix = f" — {details}" if details else ""
        print(f"  ❌ {name}{suffix}")
        _FAIL += 1
        _ERRORS.append(name)


def section(title: str) -> None:
    print(f"\n🔷 {title}")


# ═══════════════════════════════════════════════════════════
print("=" * 60)
print("スモークテスト開始")
print("=" * 60)

# ── 1. モジュールインポート ─────────────────────────────────
section("1. モジュールインポート")

run_teams = None
sms = None
try:
    import run_teams as _rt
    run_teams = _rt
    test("run_teams のインポート", True)
except Exception as e:
    test("run_teams のインポート", False, str(e))

try:
    import stock_mcp_server as _sms
    sms = _sms
    test("stock_mcp_server のインポート", True)
except Exception as e:
    test("stock_mcp_server のインポート", False, str(e))


# ── 2. _score_num ───────────────────────────────────────────
section("2. _score_num（score → 整数変換）")

if run_teams is not None:
    fn = run_teams._score_num
    test('"5/7" → 5', fn({"score": "5/7"}) == 5)
    test('"7/7" → 7', fn({"score": "7/7"}) == 7)
    test("int 3 → 3", fn({"score": 3}) == 3)
    test("None → 0", fn({"score": None}) == 0)
    test("missing → 0", fn({}) == 0)
    test('"invalid" → 0', fn({"score": "invalid"}) == 0)


# ── 3. _rs26w ───────────────────────────────────────────────
section("3. _rs26w（RS 値抽出）")

if run_teams is not None:
    fn = run_teams._rs26w
    test("rs50w 優先", fn({"rs50w": 1.5, "rs26w": 2.0}) == 1.5)
    test("rs26w フォールバック", fn({"rs26w": 1.0}) == 1.0)
    test("missing → 0.0", fn({}) == 0.0)
    test("None → 0.0", fn({"rs50w": None}) == 0.0)


# ── 4. screen_to_list ───────────────────────────────────────
section("4. screen_to_list（dict/list 変換）")

if run_teams is not None:
    fn = run_teams.screen_to_list
    d = {"7203": {"code": "7203", "score": "5/7"}, "9432": {"code": "9432", "error": "fail"}}
    result = fn(d)
    test("dict 形式: エラー除外で 1 件", len(result) == 1)
    test("dict 形式: 7203 を抽出", bool(result) and result[0].get("code") == "7203")
    l = [{"code": "7203"}, {"error": "fail"}]
    result = fn(l)
    test("list 形式: エラー除外で 1 件", len(result) == 1)
    test("空 dict → []", fn({}) == [])
    test("None → []", fn(None) == [])


# ── 5. detect_phase ─────────────────────────────────────────
section("5. detect_phase（フェーズ判定）")

if run_teams is not None:
    fn = run_teams.detect_phase
    result = fn([])
    test("空データ → dict 返却", isinstance(result, dict))
    test("空データ → phase=Defend", result.get("phase") == "Defend")
    sample = [{"code": str(i), "score": "7/7", "rs50w": 1.8} for i in range(15)]
    result = fn(sample)
    test("Attack 条件 → phase=Attack", result.get("phase") == "Attack")
    test("返却に score 含む", "score" in result)
    test("返却に reasons 含む", isinstance(result.get("reasons"), list))


# ── 6. screen_full_results.json 実データ整合性 ─────────────
section("6. screen_full_results.json（実データ）")

json_path = ROOT / "data" / "screen_full_results.json"
if json_path.exists():
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        test("JSON 読み込み成功", True)
        test("dict 形式（コードキー）", isinstance(data, dict))
        test("1000+ 銘柄含む", len(data) >= 1000)
        if run_teams is not None:
            lst = run_teams.screen_to_list(data)
            test("screen_to_list で list 化成功", len(lst) > 0)
            result = run_teams.detect_phase(lst)
            test("実データで detect_phase が dict 返却", isinstance(result, dict))
            test("実データ phase が有効値", result.get("phase") in ("Attack", "Steady", "Defend"))
    except Exception as e:
        test("JSON 読み込み成功", False, str(e))
else:
    test("screen_full_results.json 存在", False, str(json_path))


# ── 7. _minervini（ミネルヴィニスコア） ─────────────────────
section("7. _minervini（ミネルヴィニ 7 条件スコア）")

if sms is not None:
    try:
        import pandas as pd
        closes = [100 + i * 0.5 for i in range(60)]
        df = pd.DataFrame({"close": closes})
        result = sms._minervini(df)
        test("戻り値が dict", isinstance(result, dict))
        test("error フィールドなし", "error" not in result)
        test("score キーあり", "score" in result)
        test("conditions が長さ 7 の配列", len(result.get("conditions", [])) == 7)
        short_df = pd.DataFrame({"close": [100, 101, 102]})
        result2 = sms._minervini(short_df)
        test("短いデータ（3 日）→ error", "error" in result2)
    except Exception as e:
        test("_minervini テスト", False, str(e))


# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print(f"結果: ✅ {_PASS} 合格 / ❌ {_FAIL} 失敗")
if _ERRORS:
    print("\n失敗項目:")
    for e in _ERRORS:
        print(f"  - {e}")
print("=" * 60)

sys.exit(0 if _FAIL == 0 else 1)

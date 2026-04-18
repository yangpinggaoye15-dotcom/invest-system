"""Team 1: 情報収集チーム（米国・日本・マクロ地政学）

run_teams.py から抽出。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from teams._base import (
    call_claude, call_gemini, save_source_log,
    load_json, _fetch_fresh_price,
    read_report, is_generated, screen_to_list, _score_num, _rs26w, write_report,
    save_kpi_log, build_kpi_check_prompt,
    read_shared_context, update_shared_context, get_feedback_prefix,
    read_knowledge, write_knowledge,
    LABEL_RULE, SHARED_CTX_PATH, KNOWLEDGE_DIR,
)
from teams._config import TEAM_KPIS, SOURCE_RELIABILITY
from teams._context import (
    TODAY, WEEKDAY, IS_MARKET_DAY,
    DAY_MODE, DAY_LABEL, DAY_FOCUS,
    DATA_DIR, REPORT_DIR,
    client, MODEL, GEMINI_KEY, GEMINI_URL,
)
from teams._tools import _run_agent_team
from teams._phase import detect_phase
from teams._scenarios import (
    MAX_SIM_SLOTS,
    _make_new_sim, _get_week_target, _determine_leading_scenario,
    _scenario_gaps, _generate_scenarios, _analyze_daily_deviation,
    _get_sector_group, _check_sector_diversity, _weekly_scenario_review,
)


# ─── Team 1: 情報収集 ────────────────────────────────────────────
def run_info_gathering():
    print(f'  [エージェント起動] 情報収集チーム ({DAY_LABEL})')

    system = _agent_system_prompt(
        '情報収集チーム',
        '市場情報を正確・迅速に収集し、後続チームに届ける。'
        '指数・為替・金利・コモディティ・イベント・セクター・ニュース・RS上位の8項目を必ず網羅する。'
        'データの正確性を最優先し、不明な場合は「情報なし」と明記する。'
    )

    initial = f"""本日{TODAY}（{DAY_LABEL}）の情報収集レポートを作成してください。

【手順】
1. read_knowledge("info_patterns") で過去の収集パターン・発見を確認
2. search_market_info で本日の市場データを収集（平日は複数クエリ推奨）:
   - "{TODAY} 日経平均 終値 TOPIX 前日比"
   - "{TODAY} S&P500 NASDAQ ダウ 為替 ドル円"
   - "{TODAY} 米10年債利回り WTI金 重要イベント"
   - "{TODAY} 日本株 ニュース 材料 セクター"
3. get_screening_data(top_n=10) でRS上位銘柄を確認
4. write_knowledge("info_patterns") で今日の重要な発見・パターンを保存
5. finalize_report でレポートを完成させる

【レポートフォーマット】
# 情報収集チーム レポート [{DAY_LABEL}]
日付: {TODAY}
✅ 検証済み（情報収集チームリーダー確認）

## 市場概況
（表形式: 指数・終値・前日比）

## 為替・コモディティ・金利

## 本日の注目イベント・スケジュール

## セクター動向

## 注目ニュース（3件以上）

## スクリーニング状況（RS上位）

## 翌日・来週の注目点

---
{'週末のため市場データは限定的。ニュース・マクロ環境に集中してください。' if not IS_MARKET_DAY else '平日なので市場データを完全収集してください。'}"""

    _run_agent_team('info', '情報収集チーム', system, initial, 'info_gathering')



"""Team 3: リスク管理チーム（ポジション・損切り・DD 管理）

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


# ─── Team 3: リスク管理 ──────────────────────────────────────────
def run_risk_management():
    print(f'  [エージェント起動] リスク管理チーム ({DAY_LABEL})')

    system = _agent_system_prompt(
        'リスク管理チーム',
        '資産を守り、ルールベースのリスク管理を徹底する。'
        '損切りライン: -7〜8% / 最大DD: -10% / セクター集中上限: 30%。'
        '現金100%モード時はDD・損切り・セクター集中度は「対象外（✅）」として記録する。'
    )

    initial = f"""本日{TODAY}（{DAY_LABEL}）のリスク管理レポートを作成してください。

【手順】
1. read_knowledge("risk_patterns") で過去のリスク管理パターンを確認
2. get_portfolio() でポートフォリオ状況を確認（現金100%かどうかを確認）
3. read_past_report("info_gathering", max_chars=1000) で市場環境を把握
4. read_past_report("analysis", max_chars=800) で銘柄評価を確認
5. search_market_info で現在のリスク要因を収集:
   - "{TODAY} VIX 信用スプレッド マクロリスク"
   - "{TODAY} 地政学リスク 市場下落 要因"
6. get_simulation_status() でシミュレーション状況も参考に
7. write_knowledge("risk_patterns") で今日の重要なリスク発見を保存
8. finalize_report でレポートを完成させる

【レポートフォーマット】
# リスク管理チーム レポート [{DAY_LABEL}]
日付: {TODAY}

## ポートフォリオ概況

## リスク指標（損切り-7%・DD-10%・セクター集中30%基準）
| 項目 | 現状 | 警戒水準 | 評価 |
|------|------|----------|------|

## 保有銘柄リスク評価

## 市場リスク（VIX・マクロ・地政学）

## 損切り/縮小候補

## 推奨アクション（優先順）"""

    _run_agent_team('risk', 'リスク管理チーム', system, initial, 'risk')



"""Team 4: 投資戦略チーム（フェーズ判定・エントリー設計）

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


# ─── Team 4: 投資戦略 ────────────────────────────────────────────
def run_strategy():
    print(f'  [エージェント起動] 投資戦略チーム ({DAY_LABEL})')

    # ルールベースのフェーズ事前判定（AIへの参考情報として渡す）
    screen = load_json('screen_full_results.json', {})
    auto_phase = detect_phase(screen_to_list(screen))
    auto_phase_str = (
        f"ルールベース判定: {auto_phase['phase']} (スコア: {auto_phase['score']})\n"
        + '\n'.join(f"  - {r}" for r in auto_phase['reasons'])
    )

    # 前回監査の改善提案
    strategy_feedback = get_feedback_prefix('strategy')

    system = _agent_system_prompt(
        '投資戦略チーム',
        '市場フェーズを正確に判定し、具体的なエントリー計画を立案する。'
        'Attack/Steady/Defendの判定根拠を3点以上明記。'
        'エントリー候補テーブルには銘柄名・コード・価格・損切り・目標・RR比・根拠を全て記載する。' +
        f'\n\n【ルールベース自動判定（参考）】\n{auto_phase_str}' +
        (f'\n\n【前回監査の改善提案】\n{strategy_feedback}' if strategy_feedback.strip() else '')
    )

    initial = f"""本日{TODAY}（{DAY_LABEL}）の投資戦略レポートを作成してください。

【手順】
1. read_knowledge("strategy_patterns") で過去の戦略パターン・フェーズ判定精度を確認
2. read_past_report("info_gathering", max_chars=1200) で市場環境を把握
3. read_past_report("analysis", max_chars=1500) で銘柄評価を確認
4. read_past_report("risk", max_chars=800) でリスク評価を確認
5. get_screening_data(min_score=6) で現在の銘柄強度を確認
6. search_market_info で需給・センチメント情報を収集:
   - "{TODAY} 日本株 機関投資家 需給 外国人売買"
   - "{TODAY} Put/Call比率 VIX Fear&Greed センチメント"
7. write_knowledge("strategy_patterns") で今日のフェーズ判定・有効だった戦略を保存
8. finalize_report でレポートを完成させる

【フェーズ判定基準】
- Attack: 市場トレンド上向き、RS上位銘柄が続々ブレイク、VIX低位安定
- Steady: トレンド中立、選別的エントリー可能
- Defend: 市場下落トレンド、現金保有が最優先

【レポートフォーマット】
# 投資戦略チーム レポート [{DAY_LABEL}]
日付: {TODAY}

## 市場環境判定: [Attack/Steady/Defend]
**判定理由**（根拠3点以上必須）

## 需給・センチメント評価

## 新規エントリー候補
| 銘柄 | コード | EP | 損切り | 目標① | RR比 | 推奨サイズ | 根拠 |
|------|--------|-----|--------|-------|------|-----------|------|

## エントリー見送り理由

## 本日のアクションプラン（優先順）

## 来週以降の注目点"""

    _run_agent_team('strategy', '投資戦略チーム', system, initial, 'strategy')



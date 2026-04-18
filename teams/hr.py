"""Team 9: 人事部（チームパフォーマンス・MVP 選出・週次土曜）

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


# ─── Team 9: 人事部（週次・土曜実行） ────────────────────────────
def run_hr():
    """週次KPIランキング・インセンティブ設計・hr_report.md生成"""
    if DAY_MODE not in ('saturday', 'weekday'):
        print('  [人事部] 平日・土曜以外はスキップ')
        return

    print(f'  [エージェント起動] 人事部 ({DAY_LABEL})')

    # KPIログから直近7日分を計算して渡す
    log_path = REPORT_DIR / 'kpi_log.json'
    kpi_log = []
    if log_path.exists():
        try:
            kpi_log = json.loads(log_path.read_text(encoding='utf-8'))
        except Exception:
            pass
    recent = kpi_log[-7:] if kpi_log else []

    TEAM_NAMES_JP = {
        'info': '情報収集チーム', 'analysis': '銘柄選定・仮説チーム',
        'risk': 'リスク管理チーム', 'strategy': '投資戦略チーム',
        'report': 'レポート統括', 'verification': 'シミュレーション追跡・検証チーム',
        'security': 'セキュリティチーム', 'audit': '内部監査チーム',
    }

    team_scores: dict[str, list[float]] = {}
    for entry in recent:
        for t_key, scores in entry.get('teams', {}).items():
            if isinstance(scores, dict):
                avg = sum(scores.values()) / len(scores) if scores else 0
                team_scores.setdefault(t_key, []).append(avg)
    team_avg = {k: round(sum(v) / len(v), 1) for k, v in team_scores.items()}
    ranked = sorted(team_avg.items(), key=lambda x: x[1], reverse=True)
    ranking_str = '\n'.join(
        f'{i+1}位: {TEAM_NAMES_JP.get(k, k)} — {v}点'
        for i, (k, v) in enumerate(ranked)
    ) if ranked else '（データなし）'

    mvp_key = ranked[0][0] if ranked else ''
    mvp_name = TEAM_NAMES_JP.get(mvp_key, mvp_key)
    mvp_score = ranked[0][1] if ranked else 0

    system = _agent_system_prompt(
        '人事部（CPO）',
        '全チームのKPIスコアを評価し、インセンティブ設計と改善指示を行う。'
        'Phase1目標: 月次+16.7%・勝率50%・PF2.0・DD10%以内。' +
        f'\n\n【直近7日間のKPIランキング】\n{ranking_str}\n【MVP（暫定）】{mvp_name}（{mvp_score}点）'
    )

    initial = f"""本日{TODAY}（{DAY_LABEL}）の人事部週次レポートを作成してください。

【手順】
1. read_knowledge("hr_patterns") で過去のKPIトレンド・インセンティブ効果を確認
2. get_kpi_history(days=14) でKPI推移詳細を確認
3. read_past_report("internal_audit", max_chars=1000) で監査評価を確認
4. read_past_report("verification", max_chars=800) でシミュレーション精度を確認
5. get_simulation_status() で現在の成績を確認
6. write_knowledge("hr_patterns") で今日のKPIパターン・インセンティブ提案を保存
7. finalize_report でレポートを完成させる

【レポートフォーマット（200行以内）】
# 人事部 週次レポート [{TODAY}]

## 週次KPIランキング
| 順位 | チーム | スコア | 前週比 | 評価コメント |

## 今週のMVP（根拠・他チームへのメッセージ）

## 要注意チームへの改善指示（チーム名・具体的アクション・期限）

## 来週のインセンティブ設計
### 全チームへ（プロンプト冒頭注入用メッセージ）
### MVP特別指示

## 組織KGI達成状況（Phase1: 月次+16.7%・勝率50%・PF2.0・DD10%以内）

## 来週の重点目標（1〜2項目）"""

    result = _run_agent_team('hr', '人事部', system, initial, 'hr_report')
    print(f'  -> hr_report.md 更新 (MVP: {mvp_name} {mvp_score}点)')


# ─── メイン ──────────────────────────────────────────────────────

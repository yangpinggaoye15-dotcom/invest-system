"""Team 7: 内部監査チーム（KPI 評価・PDCA 推進）

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


# ─── Team 7: 内部監査 ─────────────────────────────────────────────
def run_internal_audit():
    print(f'  [エージェント起動] 内部監査チーム ({DAY_LABEL})')

    # 前回監査ログ（フォローアップ用）
    audit_log_path = Path('reports') / 'audit_log.md'
    prev_audit = audit_log_path.read_text(encoding='utf-8')[-2000:] if audit_log_path.exists() else '（初回）'

    # KPI定義を注入
    kpi_definitions = build_kpi_check_prompt()

    system = _agent_system_prompt(
        '内部監査チーム',
        '全チームのKPI達成状況を評価し、継続的改善サイクルを推進する。'
        '評価軸: 網羅性・具体性・有用性・一貫性・連携性・AI活用度（各5段階）。'
        '全チームに評価スコアを付け、改善提案を優先度高・中で2件以上出すこと。' +
        f'\n\n{kpi_definitions}' +
        f'\n\n【前回の監査ログ（フォローアップ用）】\n{prev_audit[:1000]}'
    )

    initial = f"""本日{TODAY}の内部監査レポートを作成してください。

【手順】
1. read_knowledge("audit_patterns") で過去の監査発見・改善トレンドを確認
2. 各チームレポートをread_past_reportで読む:
   - info_gathering, analysis, risk, strategy（各1500字程度）
   - security, latest_report（各1000字程度）
3. get_kpi_history(days=14) でKPIトレンドを確認
4. search_market_info で投資チームのベストプラクティスを収集:
   - "ミネルヴィニ 成長株投資 AI分析 ベストプラクティス"
5. write_knowledge("audit_patterns") で今日の監査発見を保存
6. finalize_report でレポートを完成させる

【レポートフォーマット（チーム別評価スコアテーブルを必ず含める）】
# 内部監査チーム レポート
日付: {TODAY}

## エグゼクティブサマリー（最重要発見3点以内）

## KPI達成状況
| チーム | KPI項目 | 目標 | 達成状況 | 評価 |
|--------|---------|------|---------|------|

## チーム別評価スコア
| チーム | 網羅性 | 具体性 | 有用性 | 一貫性 | 連携性 | AI活用度 | 総合 | 所見 |
|--------|--------|--------|--------|--------|--------|---------|------|------|
| 情報収集 | /5 | /5 | /5 | /5 | /5 | /5 | /5 | ... |
| 分析 | /5 | /5 | /5 | /5 | /5 | /5 | /5 | ... |
| リスク管理 | /5 | /5 | /5 | /5 | /5 | /5 | /5 | ... |
| 投資戦略 | /5 | /5 | /5 | /5 | /5 | /5 | /5 | ... |
| 統括 | /5 | /5 | /5 | /5 | /5 | /5 | /5 | ... |
| セキュリティ | /5 | /5 | /5 | /5 | /5 | /5 | /5 | ... |

## KPIトレンド分析

## 改善提案
### 優先度: 高（KPI未達成に直結）
### 優先度: 中（品質向上）

## 前回提案のフォローアップ"""

    result = _run_agent_team('audit', '内部監査チーム', system, initial, 'internal_audit')

    # KPIログ保存（チーム別スコア → kpi_log.json）
    _TEAM_KEY_MAP = {
        '情報収集': 'info', '分析': 'analysis', '銘柄選定・仮説': 'analysis',
        'リスク管理': 'risk', '投資戦略': 'strategy',
        '統括': 'report', 'レポート統括': 'report',
        'セキュリティ': 'security',
        '検証': 'verification', 'シミュレーション追跡': 'verification',
        '内部監査': 'audit',
    }
    def _parse_score(s):
        s = s.strip()
        if '/' in s:
            try:
                n, d = s.split('/', 1)
                return round(float(n.strip()) / float(d.strip()) * 10, 1)
            except Exception:
                return None
        try:
            return float(s)
        except Exception:
            return None

    kpi_scores = {}
    _score_keys = ['coverage', 'specificity', 'usefulness', 'consistency', 'linkage', 'ai_usage']
    for line in result.split('\n'):
        parts = [p.strip() for p in line.split('|') if p.strip()]
        if len(parts) < 8:
            continue
        eng_key = next((v for k, v in _TEAM_KEY_MAP.items() if k in parts[0]), None)
        if not eng_key:
            continue
        try:
            scores = {}
            for i, name in enumerate(_score_keys):
                v = _parse_score(parts[i + 1]) if i + 1 < len(parts) else None
                if v is not None:
                    scores[name] = v
            total_v = _parse_score(parts[7]) if len(parts) > 7 else None
            if total_v is not None:
                scores['total'] = total_v
            if scores:
                kpi_scores[eng_key] = scores
        except (IndexError, ValueError):
            pass
    if kpi_scores:
        save_kpi_log(kpi_scores)

    # 監査ログに追記
    summary_lines = [l for l in result.split('\n') if l.startswith('- ') or l.startswith('### 優先度')][:10]
    log_entry = f'\n## {TODAY}\n' + '\n'.join(summary_lines) + '\n'
    existing = audit_log_path.read_text(encoding='utf-8') if audit_log_path.exists() else '# 内部監査ログ\n'
    audit_log_path.write_text(existing + log_entry, encoding='utf-8')
    print(f'  -> audit_log.md 更新')



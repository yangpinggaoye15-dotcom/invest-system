"""Team 6: セキュリティチーム

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


# ─── Team 6: セキュリティ ─────────────────────────────────────────
def run_security():
    import subprocess
    print(f'  [エージェント起動] セキュリティチーム ({DAY_LABEL})')

    git_log = subprocess.run(
        ['git', 'log', '--oneline', '-20'],
        capture_output=True, text=True
    ).stdout

    system = _agent_system_prompt(
        '情報セキュリティチーム',
        'コードとシステムの安全性を監視し、脅威を早期検知する。'
        '重大脆弱性（CRITICAL/HIGH）は必ず報告する。'
        '既知の安全設計: APIキーはVercel環境変数で管理・Gemini APIキーはHTTPヘッダーで送らない（CORS対策）。'
        f'\n\n【Gitコミット履歴（直近20件）】\n{git_log}'
    )

    initial = f"""本日{TODAY}のセキュリティ監査レポートを作成してください。

【手順】
1. read_knowledge("security_patterns") で過去の脅威パターン・発見を確認
2. search_market_info で最新のセキュリティ脅威情報を収集:
   - "{TODAY} Python GitHub Actions Vercel セキュリティ 脆弱性 CVE"
   - "{TODAY} 金融システム サイバー攻撃 AIapi セキュリティ"
3. write_knowledge("security_patterns") で今日の脅威情報を保存
4. finalize_report でレポートを完成させる

【内部チェック項目】
- コミットメッセージに key/secret/password/token が含まれていないか
- index.htmlに外部CDNスクリプトが追加されていないか（プロジェクトルールで禁止）
- APIキーがハードコードされていないか（sk- / AIza / Bearer パターン）
- Vercel serverless関数（api/claude.js, api/gemini.js）の実装に問題がないか
- GitHub Actions workflowにシークレット漏洩リスクがないか

【レポートフォーマット】
# 情報セキュリティチーム レポート
日付: {TODAY}

## 総合評価: [GREEN / YELLOW / RED]

## 内部監査結果
| 項目 | 状態 | 詳細 |
|------|------|------|
| コミット履歴 | ✅/⚠️/❌ | ... |
| CDNスクリプト | ✅/⚠️/❌ | ... |
| APIキー露出 | ✅/⚠️/❌ | ... |
| Vercelプロキシ | ✅/⚠️/❌ | ... |
| GitHub Actions | ✅/⚠️/❌ | ... |

## 外部脅威情報（Gemini収集）

## 要対応事項（なければ「なし」）

## 推奨事項"""

    _run_agent_team('security', 'セキュリティチーム', system, initial, 'security')



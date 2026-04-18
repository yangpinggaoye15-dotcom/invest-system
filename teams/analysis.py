"""Team 2: 銘柄選定・仮説チーム（テクニカル・ファンダ・パターン）

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


# ─── Team 2: 分析 ────────────────────────────────────────────────
def run_analysis():
    print(f'  [エージェント起動] 銘柄選定・仮説チーム ({DAY_LABEL})')

    # 前回監査の改善提案を注入（継続改善ループ）
    feedback_prefix = get_feedback_prefix('analysis')

    system = _agent_system_prompt(
        '銘柄選定・仮説チーム',
        'ミネルヴィニStage-2基準でAランク銘柄を選定し、エントリー仮説を立案する。'
        'テクニカル（MA配置・RS）・ファンダメンタル（成長率・業績グレード）・出来高（機関動向）の3軸で評価。'
        'Aランク判定には必ず根拠3つ以上を明記すること。' +
        (f'\n\n【前回監査の改善提案】\n{feedback_prefix}' if feedback_prefix.strip() else '')
    )

    initial = f"""本日{TODAY}（{DAY_LABEL}）の銘柄選定・仮説レポートを作成してください。

【手順】
1. read_knowledge("analysis_patterns") で過去の分析パターン・的中傾向を確認
2. read_past_report("info_gathering") で本日の市場環境を把握
3. get_screening_data(min_score=6, top_n=20) でスコア6以上のRS上位銘柄を取得
4. 注目銘柄のget_fins_dataで財務データ確認（上位5銘柄程度）
5. search_market_info で上位銘柄の最新情報・材料を収集
6. write_knowledge("analysis_patterns") で今日の発見・有効だったパターンを保存
7. finalize_report でA/B/Cランク付きレポートを完成させる

【分析基準（ミネルヴィニStage-2）】
- テクニカル: 株価>SMA50>SMA150>SMA200、SMA200上昇中、52週高値の75%以上
- RS: RS50wがプラスかつ高水準
- ファンダ: 売上・利益前年比20%以上成長（業績GradeはS/Aのみをエントリー対象）
- 出来高: ブレイクアウト時は平均の1.5倍以上が理想（vol_ratio≥1.5）

【レポートフォーマット】
# 銘柄選定・仮説チーム レポート [{DAY_LABEL}]
日付: {TODAY}
✅ 検証済み（銘柄選定・仮説チームリーダー確認）

## 市場環境評価

## 銘柄別分析

### Aランク（エントリー候補）
#### [銘柄名]（コード）
- **テクニカル判断**: （MA配置・RS状態）
- **ファンダ判断**: （成長率・業績グレード）
- **出来高分析**: （vol_ratio・機関動向示唆）
- **最新材料**: （ニュース・材料）
- **ランクA判定理由**: （根拠3つ以上必須）
- **リスク要因**: （懸念点）

### Bランク（ウォッチ継続）
### Cランク（様子見）

## 翌日仮説（Aランク銘柄の方向・根拠・信頼度）

## 総合所見"""

    _run_agent_team('analysis', '銘柄選定・仮説チーム', system, initial, 'analysis')



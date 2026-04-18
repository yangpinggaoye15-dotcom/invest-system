#!/usr/bin/env python3
"""
Investment Team System — 9 チーム自動実行エントリポイント
各チームが Claude / Gemini API を呼び出してレポートを生成する
"""
import json
import os
import sys
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# teams/ モジュール化: 共通設定と runtime context を分離
from teams._config import TEAM_KPIS, SOURCE_RELIABILITY
from teams._context import (
    JST, NOW_JST, TODAY, WEEKDAY, IS_MARKET_DAY,
    DAY_MODE, DAY_LABEL, DAY_FOCUS,
    DATA_DIR, REPORT_DIR,
    client, MODEL, GEMINI_KEY, GEMINI_URL,
)


from teams._base import (
    call_claude, call_gemini, save_source_log,
    load_json, _fetch_fresh_price,
    read_report, is_generated, screen_to_list, _score_num, _rs26w, write_report,
    save_kpi_log, build_kpi_check_prompt,
    read_shared_context, update_shared_context, get_feedback_prefix,
    read_knowledge, write_knowledge,
    LABEL_RULE, SHARED_CTX_PATH, KNOWLEDGE_DIR,
)


from teams._tools import (
    AGENT_TOOLS, _execute_tool, _agent_system_prompt, _run_agent_team,
)
from teams._phase import detect_phase
from teams._scenarios import (
    MAX_SIM_SLOTS,
    _make_new_sim, _get_week_target, _determine_leading_scenario,
    _scenario_gaps, _generate_scenarios, _analyze_daily_deviation,
    _get_sector_group, _check_sector_diversity, _weekly_scenario_review,
)


from teams.info import run_info_gathering
from teams.analysis import run_analysis
from teams.risk import run_risk_management
from teams.strategy import run_strategy
from teams.report import run_daily_report
from teams.verification import run_verification
from teams.security import run_security
from teams.audit import run_internal_audit
from teams.hr import run_hr


TEAMS = {
    'info':         ('情報収集チーム',   run_info_gathering),
    'analysis':     ('銘柄選定・仮説チーム',       run_analysis),
    'risk':         ('リスク管理チーム', run_risk_management),
    'strategy':     ('投資戦略チーム',   run_strategy),
    'report':       ('レポート統括',     run_daily_report),
    'verification': ('シミュレーション追跡・検証チーム',       run_verification),
    'security':     ('セキュリティチーム', run_security),
    'audit':        ('内部監査チーム',   run_internal_audit),
    'hr':           ('人事部',           run_hr),
}

# チームキー → レポートファイル名のマッピング（shared_context更新用）
TEAM_REPORT_MAP = {
    'info':         'info_gathering',
    'analysis':     'analysis',
    'risk':         'risk',
    'strategy':     'strategy',
    'report':       'latest_report',
    'verification': 'verification',
    'security':     'security',
    'audit':        'internal_audit',
    'hr':           'hr_report',
}

if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else 'all'

    # shared_context をその日の日付でリセット（allモード時のみ）
    if target == 'all':
        SHARED_CTX_PATH.write_text(f'# shared_context.md（{TODAY}更新）\n全チームの結論・重要情報を共有するハブ。各チームは必ずこの情報を参照すること。\n', encoding='utf-8')

    if target == 'all':
        for key, (name, fn) in TEAMS.items():
            print(f'\n[{name}] 開始...')
            try:
                fn()
                # ── shared_context 自動更新（各チームの結論を全チームに共有） ──
                report_name = TEAM_REPORT_MAP.get(key)
                if report_name:
                    report_text = read_report(report_name)
                    # 先頭300文字をサマリーとして共有
                    summary = report_text[:400].replace('\n', ' ').strip()
                    update_shared_context(name, summary)
                print(f'[{name}] 完了')
            except Exception as e:
                print(f'[{name}] エラー: {e}', file=sys.stderr)
    elif target in TEAMS:
        name, fn = TEAMS[target]
        print(f'[{name}] 開始...')
        fn()
        report_name = TEAM_REPORT_MAP.get(target)
        if report_name:
            summary = read_report(report_name)[:400].replace('\n', ' ').strip()
            update_shared_context(name, summary)
        print(f'[{name}] 完了')
    else:
        print(f'不明なチーム: {target}')
        print(f'使用可能: {list(TEAMS.keys())} または all')
        sys.exit(1)

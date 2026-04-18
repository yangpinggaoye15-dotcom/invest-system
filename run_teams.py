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


# ─── エージェントツール定義 ────────────────────────────────────────────────
AGENT_TOOLS = [
    {
        'name': 'search_market_info',
        'description': 'Gemini Google SearchでリアルタイムWebから市場情報・ニュース・銘柄情報を検索する。複数回呼び出し可能。',
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': '検索クエリ（日本語可。具体的な数値・銘柄名・指数名を含めると精度が上がる）'}
            },
            'required': ['query']
        }
    },
    {
        'name': 'get_screening_data',
        'description': 'J-Quantsスクリーニング結果を取得する。全銘柄のRS50w・ミネルヴィニスコア・価格・出来高比率を含む。',
        'input_schema': {
            'type': 'object',
            'properties': {
                'min_score': {'type': 'integer', 'description': '最小ミネルヴィニスコア（0-7）。デフォルト0', 'default': 0},
                'top_n': {'type': 'integer', 'description': 'RS順上位N件。デフォルト20', 'default': 20}
            }
        }
    },
    {
        'name': 'get_fins_data',
        'description': '特定銘柄の財務データ（決算・営業利益成長率・業績グレードS/A/B/C/D）を取得する。',
        'input_schema': {
            'type': 'object',
            'properties': {
                'code': {'type': 'string', 'description': '銘柄コード（4桁、例: "6857"）'}
            },
            'required': ['code']
        }
    },
    {
        'name': 'get_portfolio',
        'description': '現在のポートフォリオ・監視銘柄リストを取得する。',
        'input_schema': {
            'type': 'object',
            'properties': {
                'type': {
                    'type': 'string',
                    'enum': ['portfolio', 'watchlist', 'both'],
                    'description': '取得対象（portfolio/watchlist/both）',
                    'default': 'both'
                }
            }
        }
    },
    {
        'name': 'read_past_report',
        'description': '本日または過去に生成されたチームレポートを読む。他チームの分析結果を参照するときに使用。',
        'input_schema': {
            'type': 'object',
            'properties': {
                'report_name': {
                    'type': 'string',
                    'description': 'レポート名: info_gathering, analysis, risk, strategy, verification, security, internal_audit, hr_report, latest_report'
                },
                'max_chars': {'type': 'integer', 'description': '最大文字数（デフォルト2000）', 'default': 2000}
            },
            'required': ['report_name']
        }
    },
    {
        'name': 'get_simulation_status',
        'description': '現在のシミュレーション追跡状況（アクティブ銘柄・損益・勝率）を取得する。',
        'input_schema': {'type': 'object', 'properties': {}}
    },
    {
        'name': 'get_kpi_history',
        'description': '過去のチームKPIスコア履歴を取得する。チーム別のパフォーマンストレンドを把握できる。',
        'input_schema': {
            'type': 'object',
            'properties': {
                'days': {'type': 'integer', 'description': '取得日数（デフォルト14）', 'default': 14}
            }
        }
    },
    {
        'name': 'read_knowledge',
        'description': '過去の実行で蓄積した知識・パターン・洞察を読む。継続的学習のために重要。毎回の実行冒頭に呼ぶこと。',
        'input_schema': {
            'type': 'object',
            'properties': {
                'key': {'type': 'string', 'description': '知識キー（例: "info_patterns", "analysis_patterns", "market_cycles"）'},
                'max_chars': {'type': 'integer', 'description': '最大文字数（デフォルト3000）', 'default': 3000}
            },
            'required': ['key']
        }
    },
    {
        'name': 'write_knowledge',
        'description': '今日の重要な洞察・発見・パターンを将来の参考のために保存する。直近30回分を自動保持。',
        'input_schema': {
            'type': 'object',
            'properties': {
                'key': {'type': 'string', 'description': '知識キー（チーム名や分析テーマなど）'},
                'content': {'type': 'string', 'description': '保存する内容（Markdown形式）'}
            },
            'required': ['key', 'content']
        }
    },
    {
        'name': 'finalize_report',
        'description': 'レポートを完成させて保存する。分析が完了したら必ずこのツールを呼ぶこと。呼ぶとエージェントが終了する。',
        'input_schema': {
            'type': 'object',
            'properties': {
                'content': {'type': 'string', 'description': 'レポートの全内容（Markdown形式。全ての文に[事実]または[AI分析]ラベル必須）'}
            },
            'required': ['content']
        }
    }
]


def _execute_tool(name: str, params: dict, team_name: str = '') -> str:
    """エージェントのツール呼び出しを実行する"""
    try:
        if name == 'search_market_info':
            query = params.get('query', '')
            print(f'    [Gemini検索] {query[:60]}')
            text, sources = call_gemini(query)
            if sources:
                save_source_log(team_name or 'エージェント', sources, text)
            return text[:4000] if text else '（Gemini応答なし）'

        elif name == 'get_screening_data':
            screen = load_json('screen_full_results.json', {})
            stocks = screen_to_list(screen)
            min_score = params.get('min_score', 0)
            top_n = params.get('top_n', 20)
            filtered = sorted(
                [s for s in stocks if isinstance(s, dict) and _score_num(s) >= min_score],
                key=_rs26w, reverse=True
            )[:top_n]
            return json.dumps(filtered, ensure_ascii=False, indent=2)[:5000]

        elif name == 'get_fins_data':
            code = str(params.get('code', ''))
            fins = load_json('fins_data.json', {})
            if code in fins:
                return json.dumps(fins[code], ensure_ascii=False, indent=2)[:3000]
            chart = load_json('chart_data.json', {})
            if code in chart:
                return f'チャートデータ: {json.dumps(chart[code], ensure_ascii=False)[:1500]}'
            return f'（{code}の財務データなし: fins_data.jsonを確認してください）'

        elif name == 'get_portfolio':
            ptype = params.get('type', 'both')
            result = {}
            if ptype in ('portfolio', 'both'):
                result['portfolio'] = load_json('portfolio.json', {})
            if ptype in ('watchlist', 'both'):
                result['watchlist'] = load_json('watchlist.json', [])
            return json.dumps(result, ensure_ascii=False, indent=2)[:3000]

        elif name == 'read_past_report':
            report_name = params.get('report_name', '')
            max_chars = params.get('max_chars', 2000)
            content = read_report(report_name)
            return content[:max_chars] if len(content) > max_chars else content

        elif name == 'get_simulation_status':
            for p in [REPORT_DIR / 'simulation_log.json', DATA_DIR / 'reports' / 'simulation_log.json']:
                if p.exists():
                    return p.read_text(encoding='utf-8')[:4000]
            return '（シミュレーションデータなし）'

        elif name == 'get_kpi_history':
            days = params.get('days', 14)
            for p in [REPORT_DIR / 'kpi_log.json', DATA_DIR / 'reports' / 'kpi_log.json']:
                if p.exists():
                    try:
                        data = json.loads(p.read_text(encoding='utf-8'))
                        return json.dumps(data[-days:], ensure_ascii=False, indent=2)[:3000]
                    except Exception:
                        pass
            return '（KPIデータなし）'

        elif name == 'read_knowledge':
            return read_knowledge(params.get('key', ''), params.get('max_chars', 3000))

        elif name == 'write_knowledge':
            write_knowledge(params.get('key', 'unknown'), params.get('content', ''))
            return '知識保存完了'

        elif name == 'finalize_report':
            return '__FINALIZED__'

        else:
            return f'（不明なツール: {name}）'

    except Exception as e:
        return f'（ツール実行エラー [{name}]: {e}）'


def _agent_system_prompt(team_name: str, description: str) -> str:
    """全チーム共通のエージェントシステムプロンプトを生成する"""
    return f"""あなたは投資チームの「{team_name}」です。ミネルヴィニ流成長株投資システムの一部として機能します。

【本日の状況】
- 日付: {TODAY} / {DAY_LABEL}
- 市場稼働: {'はい（平日）' if IS_MARKET_DAY else 'いいえ（週末）'}
- 本日のフォーカス: {DAY_FOCUS}

【あなたのミッション】
{description}

【必須ルール】
1. 全ての情報に[事実]または[AI分析]ラベルを付ける
   - [事実]: 市場データ・数値・ニュース等の客観的事実
   - [AI分析]: AIの推論・判断・予測・解釈
2. ツールを積極的に使い、データに基づいた分析を行う
3. 最初にread_knowledgeを呼んで過去の洞察を参照する
4. 分析完了後は必ずfinalize_reportを呼ぶ（これを忘れるとレポートが保存されない）
5. 重要な発見はwrite_knowledgeで保存して学習を蓄積する

【ツール利用指針】
- 情報が足りなければsearch_market_infoを複数回呼ぶ（具体的なクエリで精度UP）
- 銘柄の詳細財務はget_fins_dataで確認する
- 他チームの分析はread_past_reportで参照する
- 週末(土日)はIS_MARKET_DAY=Falseのため市場データが限定的"""


def _run_agent_team(
    team_key: str,
    team_name: str,
    system_prompt: str,
    initial_message: str,
    report_name: str,
    max_iterations: int = 15
) -> str:
    """
    エージェントループを実行する（Claude API Tool Use）。
    エージェントはfinalize_reportを呼ぶまで自律的にツールを使い続ける。
    max_iterations: 無限ループ防止（デフォルト15回）
    """
    messages = [{'role': 'user', 'content': initial_message}]
    final_content = ''

    for iteration in range(max_iterations):
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            system=system_prompt,
            tools=AGENT_TOOLS,
            messages=messages
        )

        messages.append({'role': 'assistant', 'content': response.content})

        # テキストで自然終了
        if response.stop_reason == 'end_turn':
            text_blocks = [b.text for b in response.content if hasattr(b, 'text')]
            final_content = '\n'.join(text_blocks)
            print(f'  [エージェント:{team_name}] テキストで終了（{iteration+1}回反復）')
            break

        if response.stop_reason != 'tool_use':
            print(f'  [エージェント:{team_name}] 予期しない終了: {response.stop_reason}')
            break

        # ツール呼び出しを実行
        tool_results = []
        finalized = False

        for block in response.content:
            if block.type != 'tool_use':
                continue

            tool_name = block.name
            tool_input = block.input if isinstance(block.input, dict) else {}
            print(f'    [ツール:{iteration+1}] {tool_name}')

            if tool_name == 'finalize_report':
                final_content = tool_input.get('content', '')
                tool_results.append({
                    'type': 'tool_result',
                    'tool_use_id': block.id,
                    'content': 'レポート確定完了。エージェントを終了します。'
                })
                finalized = True
            else:
                result = _execute_tool(tool_name, tool_input, team_name)
                tool_results.append({
                    'type': 'tool_result',
                    'tool_use_id': block.id,
                    'content': result
                })

        messages.append({'role': 'user', 'content': tool_results})

        if finalized:
            print(f'  [エージェント:{team_name}] finalize_report呼び出し完了（{iteration+1}回反復）')
            break
    else:
        print(f'  [警告] {team_name}: エージェントループが上限({max_iterations})に達しました')
        if not final_content:
            final_content = f'# {team_name} レポート [{DAY_LABEL}]\n日付: {TODAY}\n\n（エージェントループが最大反復数に達しました）'

    if report_name and final_content:
        write_report(report_name, final_content)

    return final_content


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


# ─── Team 5: レポート統括 ─────────────────────────────────────────
def run_daily_report():
    print(f'  [エージェント起動] レポート統括 ({DAY_LABEL})')

    system = _agent_system_prompt(
        'レポート統括',
        '全チームの情報を統合し、投資家が即座に行動できる統合デイリーレポートを作成する。'
        '各チームレポートの要点を抽出し、矛盾がないか確認する。'
        '全チーム統合率100%・翌日注目点3件以上・[事実]/[AI分析]ラベル遵守が必須KPI。'
    )

    # 未生成チームを事前確認
    info = read_report('info_gathering')
    analysis = read_report('analysis')
    risk = read_report('risk')
    strategy = read_report('strategy')
    missing_teams = [name for name, content in [
        ('情報収集チーム', info), ('銘柄選定・仮説チーム', analysis),
        ('リスク管理チーム', risk), ('投資戦略チーム', strategy)
    ] if not is_generated(content)]
    missing_notice = f"⚠️ 未生成チーム: {', '.join(missing_teams)}" if missing_teams else "全チームレポート生成済み"

    initial = f"""本日{TODAY}（{DAY_LABEL}）の統合デイリーレポートを作成してください。

【状況】{missing_notice}

【手順】
1. read_knowledge("report_patterns") で過去の統合パターン・品質改善点を確認
2. 各チームレポートをread_past_reportで読む（既に読み込み済みだが追加詳細は参照可）
3. search_market_info で翌日・来週の追加注目情報を収集:
   - "{TODAY} 明日 決算発表 経済指標 スケジュール"
4. write_knowledge("report_patterns") で今日の統合で気づいた改善点を保存
5. finalize_report で統合レポートを完成させる（これがlatest_reportにも保存される）

【各チームレポートサマリー（既取得）】
■ 情報収集: {info[:600] if is_generated(info) else '（未生成）'}
■ 銘柄選定: {analysis[:800] if is_generated(analysis) else '（未生成）'}
■ リスク管理: {risk[:500] if is_generated(risk) else '（未生成）'}
■ 投資戦略: {strategy[:800] if is_generated(strategy) else '（未生成）'}

【レポートフォーマット】
# 📊 デイリー投資レポート {TODAY}

## エグゼクティブサマリー
（3〜5行で要点・市場環境判定・最重要アクション）

## 市場環境: [Attack/Steady/Defend]

## 本日のアクションプラン（優先順）
1. **[最優先]** ...

## 注目銘柄サマリー
| ランク | 銘柄 | コード | ポイント |

## リスク警戒事項

## 翌日以降の注目スケジュール

## 各チーム詳細（200字以内で各チームを要約）

---
Generated by Investment Team Agent System (Claude + Gemini)"""

    # エージェントが finalize_report を呼ぶと content が返る
    result = _run_agent_team('report', 'レポート統括', system, initial, f'{TODAY}_daily_report')
    if result:
        write_report('latest_report', result)


# ─── フェーズ自動判定（ルールベース） ────────────────────────────────
def detect_phase(screen_data: list) -> dict:
    """
    ミネルヴィニ基準によるルールベースフェーズ判定。
    返り値: {'phase': 'Attack'|'Steady'|'Defend', 'score': int, 'reasons': list}
    """
    score = 0  # +: 強気, -: 弱気
    reasons = []

    if not screen_data:
        return {'phase': 'Defend', 'score': -99, 'reasons': ['スクリーニングデータなし']}

    # ── 1. RS上位銘柄の割合（ブレイクアウト候補の多さ）
    total = len(screen_data)
    high_rs = [s for s in screen_data if isinstance(s, dict) and _rs26w(s) > 1.5]
    rs_ratio = len(high_rs) / total if total > 0 else 0
    if rs_ratio >= 0.15:
        score += 2
        reasons.append(f'[事実] RS26w>1.5の銘柄が{rs_ratio:.0%}（{len(high_rs)}/{total}銘柄） → 強気')
    elif rs_ratio >= 0.08:
        score += 1
        reasons.append(f'[事実] RS26w>1.5の銘柄が{rs_ratio:.0%}（{len(high_rs)}/{total}銘柄） → 中立')
    else:
        score -= 1
        reasons.append(f'[事実] RS26w>1.5の銘柄が{rs_ratio:.0%}（{len(high_rs)}/{total}銘柄） → 弱気')

    # ── 2. スコア7以上（全条件クリア）銘柄の数
    top_stocks = [s for s in screen_data if isinstance(s, dict) and _score_num(s) >= 7]
    if len(top_stocks) >= 10:
        score += 2
        reasons.append(f'[事実] スコア7以上が{len(top_stocks)}銘柄 → 強い候補多数')
    elif len(top_stocks) >= 5:
        score += 1
        reasons.append(f'[事実] スコア7以上が{len(top_stocks)}銘柄 → 候補あり')
    else:
        score -= 1
        reasons.append(f'[事実] スコア7以上が{len(top_stocks)}銘柄 → 候補少なく慎重')

    # ── 3. 平均RSスコアの方向性
    rs_values = [_rs26w(s) for s in screen_data if isinstance(s, dict) and _rs26w(s)]
    avg_rs = sum(rs_values) / len(rs_values) if rs_values else 0
    if avg_rs > 1.2:
        score += 1
        reasons.append(f'[事実] 全銘柄平均RS50w={avg_rs:.2f} → 市場全体が強い')
    elif avg_rs > 0.8:
        reasons.append(f'[事実] 全銘柄平均RS50w={avg_rs:.2f} → 中立水準')
    else:
        score -= 1
        reasons.append(f'[事実] 全銘柄平均RS50w={avg_rs:.2f} → 市場全体が弱い')

    # ── 4. 判定
    if score >= 3:
        phase = 'Attack'
    elif score >= 0:
        phase = 'Steady'
    else:
        phase = 'Defend'

    return {'phase': phase, 'score': score, 'reasons': reasons}


# ─── Team 8: シミュレーション追跡・検証チーム ────────────────────────────────────────────
MAX_SIM_SLOTS = 5  # 同時追跡上限

def _make_new_sim(best: dict) -> dict:
    """候補銘柄からシミュレーションエントリーを生成"""
    ep = best.get('price', 0) or 0
    stop_pct = 0.08
    target_pct = 0.25
    rs26w = _rs26w(best)               # rs26w / rs_26w 両キー対応・float変換
    score_n = _score_num(best)         # "5/7" 形式 → 整数
    return {
        'code': str(best.get('code', '')),
        'name': best.get('name', ''),
        'entry_price': round(ep, 0),
        'stop_loss': round(ep * (1 - stop_pct), 0),
        'target1': round(ep * (1 + target_pct), 0),
        'rr_ratio': round(target_pct / stop_pct, 1),
        'start_date': TODAY,
        'end_date': None,
        'days_elapsed': 0,
        'current_price': ep,
        'current_pct': 0.0,
        'rs_26w': rs26w,
        'score': score_n,
        'result': None,
        'result_pct': None,
        'direction_match': None,
        'reason': f"RS50w={rs26w:.2f}, score={score_n}/7, 上位候補",
        # v2: 3シナリオ・日次ログ・仮説
        'scenarios': None,        # _generate_scenarios() で生成
        'daily_log': [],
        'current_hypothesis': None,
    }


# ─── v2: 3シナリオ ヘルパー関数 ──────────────────────────────────────────────

def _get_week_target(scenarios, scenario_id, days_elapsed):
    """経過日数から対応する週のターゲット%を返す"""
    s = scenarios.get(scenario_id, {})
    if days_elapsed <= 5:    return s.get('w1_pct', 0)
    elif days_elapsed <= 10: return s.get('w2_pct', 0)
    elif days_elapsed <= 15: return s.get('w3_pct', 0)
    else:                    return s.get('w4_pct', 0)


def _determine_leading_scenario(scenarios, cumulative_pct, days_elapsed):
    """現在の累積%に最も近いシナリオを返す"""
    best, best_gap = None, float('inf')
    for sid in ('bull', 'base', 'bear'):
        target = _get_week_target(scenarios, sid, days_elapsed)
        gap = abs(cumulative_pct - target)
        if gap < best_gap:
            best_gap, best = gap, sid
    return best


def _scenario_gaps(scenarios, cumulative_pct, days_elapsed):
    """各シナリオとの乖離（cumulative - target）を返す"""
    return {sid: round(cumulative_pct - _get_week_target(scenarios, sid, days_elapsed), 2)
            for sid in ('bull', 'base', 'bear')}


def _generate_scenarios(sim, context_str='', market_phase=None):
    """新規シミュレーション銘柄に対して1ヶ月の3シナリオを生成（Claude使用）

    Args:
        sim: シミュレーション銘柄dict
        context_str: 分析レポートなどの追加コンテキスト
        market_phase: detect_phase()の返り値 {'phase': str, 'score': int, 'reasons': list}
    """
    ep = sim['entry_price']
    stop_pct = round((ep - sim['stop_loss']) / ep * 100, 1)
    target_pct = round((sim['target1'] - ep) / ep * 100, 1)

    # 機能1: フェーズ・マクロリスク情報をプロンプトに追加
    phase_str = ''
    bear_min_prob = 20  # デフォルトのbear最低確率
    if market_phase:
        phase = market_phase.get('phase', 'Steady')
        phase_score = market_phase.get('score', 0)
        phase_reasons = market_phase.get('reasons', [])
        phase_reasons_str = '\n'.join(phase_reasons[:3]) if phase_reasons else '（理由なし）'
        market_day_str = '平日（市場稼働日）' if IS_MARKET_DAY else '週末（市場休場）'
        phase_str = f"""
## 現在の市場環境（フェーズ・マクロリスク）
- 市場稼働: {market_day_str}
- 市場フェーズ: **{phase}**（スコア: {phase_score}）
- フェーズ判定根拠:
{phase_reasons_str}
- コンテキスト: {context_str[:300] if context_str else '（分析レポートなし）'}
"""
        # Defendフェーズ時はbear確率を最低35%に設定
        if phase == 'Defend':
            bear_min_prob = 35

    bear_min_note = f'bearの最低確率は{bear_min_prob}%以上にすること（現在フェーズ: {market_phase.get("phase", "Steady") if market_phase else "不明"}）。' if bear_min_prob > 20 else ''

    prompt = f"""以下の銘柄について、これから1ヶ月（20営業日）のシミュレーション追跡用に
強気・中立・弱気の3シナリオを立ててください。

銘柄: {sim['name']}（{sim['code']}）
エントリー価格: {ep}円  損切り: -{stop_pct}%  目標①: +{target_pct}%
RS26w: {sim.get('rs_26w','N/A')}  スコア: {sim.get('score','N/A')}/7
{phase_str}
## 確率設定の指示
- 現在のフェーズとマクロリスクを考慮して確率を設定すること
- {bear_min_note}
- Attackフェーズ時はbull確率を高め（35%以上）に設定すること
- Defendフェーズ時はbear確率を最低35%以上にすること（上記マクロリスク環境が深刻な場合は50%以上も検討）
- bull+base+bear の合計は必ず100にすること

## 出力（JSONのみ・説明文不要）
{{
  "bull": {{
    "label": "強気",
    "summary": "（シナリオ概要 30文字以内）",
    "w1_pct": 8.0,
    "w2_pct": 15.0,
    "w3_pct": 20.0,
    "w4_pct": 25.0,
    "trigger": "（成立条件 30文字以内）",
    "invalidation": "（崩壊条件 20文字以内）",
    "probability": 30
  }},
  "base": {{
    "label": "中立",
    "summary": "（シナリオ概要 30文字以内）",
    "w1_pct": 2.0,
    "w2_pct": 5.0,
    "w3_pct": 8.0,
    "w4_pct": 12.0,
    "trigger": "（成立条件 30文字以内）",
    "invalidation": "（崩壊条件 20文字以内）",
    "probability": 50
  }},
  "bear": {{
    "label": "弱気",
    "summary": "（シナリオ概要 30文字以内）",
    "w1_pct": -5.0,
    "w2_pct": -8.0,
    "w3_pct": -8.0,
    "w4_pct": -8.0,
    "trigger": "（成立条件 30文字以内）",
    "invalidation": "（崩壊条件 20文字以内）",
    "probability": 20
  }}
}}
注意: bull+base+bear の probability合計は必ず100にすること。w4_pctは損切り(-{stop_pct}%)〜目標(+{target_pct}%)の範囲内で設定。"""

    response = call_claude(prompt, max_tokens=800, inject_labels=False)
    try:
        import re as _re
        m = _re.search(r'\{[\s\S]*\}', response)
        if m:
            parsed = json.loads(m.group())
            # validate required keys
            for k in ('bull', 'base', 'bear'):
                if k not in parsed:
                    raise ValueError(f"missing scenario: {k}")
                for f in ('label', 'summary', 'w1_pct', 'w2_pct', 'w3_pct', 'w4_pct', 'probability'):
                    if f not in parsed[k]:
                        raise ValueError(f"missing field {f} in {k}")
            return parsed
    except Exception as e:
        print(f'  [警告] シナリオJSON解析失敗: {e}')
    # fallback: default scenarios
    return {
        'bull':  {'label': '強気', 'summary': 'RS継続上昇', 'w1_pct': 8.0,  'w2_pct': 15.0, 'w3_pct': 20.0, 'w4_pct': 25.0, 'trigger': 'ブレイクアウト継続', 'invalidation': 'SMA50割れ', 'probability': 30},
        'base':  {'label': '中立', 'summary': 'もみ合い継続', 'w1_pct': 2.0,  'w2_pct': 5.0,  'w3_pct': 8.0,  'w4_pct': 12.0, 'trigger': '市場落ち着き', 'invalidation': '出来高急減', 'probability': 50},
        'bear':  {'label': '弱気', 'summary': '調整・下落', 'w1_pct': -5.0, 'w2_pct': -8.0, 'w3_pct': -8.0, 'w4_pct': -8.0, 'trigger': '市場リスク増大', 'invalidation': '上昇転換', 'probability': 20},
    }


def _analyze_daily_deviation(sim, daily_entry, prev_hyp):
    """差異分析と翌日仮説をClaudeで生成"""
    scenarios = sim.get('scenarios', {})

    # 前日仮説との一致判定
    prev_direction = prev_hyp.get('next_day_direction', '') if prev_hyp else ''
    actual_direction = '上昇' if daily_entry['daily_pct'] > 0.3 else ('下落' if daily_entry['daily_pct'] < -0.3 else '横ばい')
    prev_match = (prev_direction == actual_direction) if prev_direction else None

    scenarios_str = json.dumps(scenarios, ensure_ascii=False, indent=2)

    prompt = f"""投資シミュレーション検証チームです。本日の値動きを分析してください。

銘柄: {sim['name']}（{sim['code']}）
エントリー: {sim['entry_price']}円 / {sim['start_date']} ({sim.get('days_elapsed',0)}営業日目)

【3シナリオ（現在確率）】
{scenarios_str}

【前日仮説】 方向={prev_direction or 'なし'} 根拠={prev_hyp.get('next_day_reason','') if prev_hyp else ''}
【実際】 価格={daily_entry['price']}円 本日={daily_entry['daily_pct']:+.1f}% 累計={daily_entry['cumulative_pct']:+.1f}%
【各シナリオとの乖離】 {daily_entry['scenario_gaps']}

JSONのみ返答（説明文不要）:
{{
  "cause": "[事実]または[AI分析]ラベルつきで差異原因50文字以内",
  "hypothesis_revision": "シナリオ修正点30文字以内（修正なしなら'修正なし'）",
  "updated_probabilities": {{"bull": 30, "base": 50, "bear": 20}},
  "next_day_direction": "上昇|下落|横ばい",
  "next_day_reason": "翌日方向の根拠40文字以内",
  "next_day_confidence": "高|中|低",
  "next_day_key_level": "注目価格水準"
}}
確率合計は必ず100にすること。"""

    response = call_claude(prompt, max_tokens=600, inject_labels=False)
    try:
        import re as _re
        m = _re.search(r'\{[\s\S]*\}', response)
        if m:
            result = json.loads(m.group())
            result['prev_match'] = prev_match
            return result
    except Exception as e:
        print(f'  [警告] 差異分析JSON解析失敗: {e}')

    return {
        'cause': '[AI分析] データ取得失敗',
        'hypothesis_revision': '修正なし',
        'updated_probabilities': {sid: scenarios[sid].get('probability', 33) for sid in scenarios} if scenarios else {'bull': 33, 'base': 34, 'bear': 33},
        'next_day_direction': '横ばい',
        'next_day_reason': 'データ不足',
        'next_day_confidence': '低',
        'next_day_key_level': '',
        'prev_match': prev_match,
    }


# ─── 機能2: セクター分散チェック ────────────────────────────────────────────────
def _get_sector_group(code_str: str, stock_data: dict = None) -> str:
    """
    銘柄コードからセクターグループを返す。
    stock_dataがあれば 'sector' / 'industry' フィールドを優先使用。
    なければコード番号範囲で簡易判定。
    """
    # データがあればsector/industryフィールドを優先
    if stock_data:
        sector = stock_data.get('sector') or stock_data.get('industry') or ''
        if sector:
            return sector

    # フィールドがなければコード番号範囲で簡易判定
    try:
        code_int = int(code_str)
        if 6200 <= code_int <= 6999:
            return '電機・精密機器・機械'
        elif 3000 <= code_int <= 3999:
            return '繊維・化学'
        elif 7000 <= code_int <= 7999:
            return '自動車・輸送'
        elif 1000 <= code_int <= 1999:
            return '農林・水産・鉱業・エネルギー'
        elif 2000 <= code_int <= 2999:
            return '食品・飲料'
        elif 4000 <= code_int <= 4999:
            return '医薬・バイオ'
        elif 5000 <= code_int <= 5999:
            return '鉄鋼・非鉄・建設・ガラス'
        elif 8000 <= code_int <= 8999:
            return '金融・不動産'
        elif 9000 <= code_int <= 9999:
            return '通信・インフラ・サービス'
        else:
            return 'その他'
    except (ValueError, TypeError):
        return 'その他'


def _check_sector_diversity(actives: list, candidate_code: str, stocks_by_code: dict) -> tuple:
    """
    セクター分散チェック: 同一セクターの銘柄が2件以上ある場合はFalseを返す。
    セクターはscreening dataの 'sector' or 'industry' フィールドを使用。
    なければ簡易判定（コード範囲: 6xxx=電機・機械, 3xxx=繊維・化学等）。

    Args:
        actives: 現在アクティブなシミュレーションリスト
        candidate_code: チェック対象の銘柄コード（str）
        stocks_by_code: {code: stock_data} のdict

    Returns:
        (bool: 追加可能か, str: 理由)
    """
    SECTOR_LIMIT = 2  # 同一セクター上限

    try:
        candidate_data = stocks_by_code.get(str(candidate_code), {})
        candidate_sector = _get_sector_group(str(candidate_code), candidate_data)

        # アクティブ銘柄の各セクターをカウント
        sector_counts = {}
        for active in actives:
            active_code = str(active.get('code', ''))
            active_data = stocks_by_code.get(active_code, {})
            sector = _get_sector_group(active_code, active_data)
            sector_counts[sector] = sector_counts.get(sector, 0) + 1

        current_count = sector_counts.get(candidate_sector, 0)
        if current_count >= SECTOR_LIMIT:
            reason = f'セクター「{candidate_sector}」はすでに{current_count}銘柄追跡中（上限: {SECTOR_LIMIT}銘柄）'
            print(f'    [セクター分散] 除外: {candidate_code} - {reason}')
            return False, reason

        return True, f'セクター「{candidate_sector}」は{current_count}銘柄（上限: {SECTOR_LIMIT}銘柄未満）→ 追加可能'
    except Exception as e:
        print(f'  [警告] セクター分散チェック失敗: {e}')
        return True, 'チェック失敗（デフォルト: 追加許可）'


# ─── 機能3: 週次シナリオ精度レビュー ─────────────────────────────────────────────
def _weekly_scenario_review(actives: list, history: list) -> str:
    """
    土曜日（DAY_MODE == 'saturday'）に実行する週次シナリオ精度レビュー。
    各追跡銘柄について week1（5営業日）の daily_log を集計し、
    実際の累積騰落率 vs 各シナリオの w1_pct を比較する。

    Args:
        actives: アクティブシミュレーションリスト
        history: 完了済みシミュレーションリスト

    Returns:
        markdown形式の週次レビュー文字列
    """
    print('  [週次レビュー] 土曜日: シナリオ精度レビュー生成中...')
    try:
        all_sims = actives + history
        review_lines = []
        scenario_lead_counts = {'bull': 0, 'base': 0, 'bear': 0}
        total_w1_entries = 0

        for sim in all_sims:
            daily_log = sim.get('daily_log', [])
            scenarios = sim.get('scenarios', {})
            if not daily_log or not scenarios:
                continue

            # week1（5営業日分）のdaily_logを取得
            w1_logs = [d for d in daily_log if isinstance(d, dict)][:5]
            if not w1_logs:
                continue

            # week1 実際の累積騰落率（最後のエントリ）
            actual_w1_pct = w1_logs[-1].get('cumulative_pct', 0)
            total_w1_entries += 1

            # 各シナリオのw1_pctとの差
            best_sid = None
            best_gap = float('inf')
            gaps_str_parts = []
            for sid in ('bull', 'base', 'bear'):
                scen = scenarios.get(sid, {})
                w1_target = scen.get('w1_pct', 0)
                gap = abs(actual_w1_pct - w1_target)
                gaps_str_parts.append(f"{sid}={w1_target:+.1f}%（差{gap:+.1f}%）")
                if gap < best_gap:
                    best_gap = gap
                    best_sid = sid

            if best_sid:
                scenario_lead_counts[best_sid] = scenario_lead_counts.get(best_sid, 0) + 1

            best_label = (scenarios.get(best_sid, {}).get('label', best_sid)) if best_sid else '不明'
            review_lines.append(
                f"- **{sim.get('name', '?')}**（{sim.get('code', '?')}）: "
                f"実績w1={actual_w1_pct:+.1f}% | {' / '.join(gaps_str_parts)} "
                f"→ **週次リードシナリオ: {best_label}**"
            )

        if not review_lines:
            return '\n## 週次シナリオ精度レビュー（土曜）\n\n（週1件以上のdaily_logデータがありません）\n'

        # シナリオ別リード回数サマリ
        bull_rate = scenario_lead_counts['bull'] / total_w1_entries * 100 if total_w1_entries else 0
        base_rate = scenario_lead_counts['base'] / total_w1_entries * 100 if total_w1_entries else 0
        bear_rate = scenario_lead_counts['bear'] / total_w1_entries * 100 if total_w1_entries else 0

        # Claudeでシナリオ確率更新提案を生成
        print('    [Claude] 週次シナリオ精度レビュー提案生成中...')
        detail_str = '\n'.join(review_lines)
        update_prompt = f"""投資シミュレーション検証チームです。今週（土曜）のシナリオ精度を振り返ってください。

## 週次シナリオ実績サマリ（追跡{total_w1_entries}銘柄）
{detail_str}

## シナリオ別 週次リード回数
- 強気（bull）リード: {scenario_lead_counts['bull']}件 ({bull_rate:.0f}%)
- 中立（base）リード: {scenario_lead_counts['base']}件 ({base_rate:.0f}%)
- 弱気（bear）リード: {scenario_lead_counts['bear']}件 ({bear_rate:.0f}%)

以下の点を簡潔に分析してください（200文字以内）:
1. 今週最も的中したシナリオパターンと理由
2. 来週のシナリオ確率設定への反映提案（例: bear確率を+5%調整）
3. 改善ポイント（シナリオ設計・確率設定の課題）

[AI分析]ラベルを付けて回答してください。"""

        try:
            claude_suggestion = call_claude(update_prompt, max_tokens=500, inject_labels=False)
        except Exception as e:
            claude_suggestion = f'[AI分析] 提案生成失敗: {e}'

        md = f"""
## 週次シナリオ精度レビュー（土曜: {TODAY}）

### 銘柄別 Week1 実績 vs シナリオ
{chr(10).join(review_lines)}

### シナリオ別リード回数（計{total_w1_entries}銘柄）
| シナリオ | リード回数 | 比率 |
|---------|----------|------|
| 強気（bull） | {scenario_lead_counts['bull']}件 | {bull_rate:.0f}% |
| 中立（base） | {scenario_lead_counts['base']}件 | {base_rate:.0f}% |
| 弱気（bear） | {scenario_lead_counts['bear']}件 | {bear_rate:.0f}% |

### Claude提案（確率設定の改善案）
{claude_suggestion}
"""
        print(f'    [週次レビュー] 完了 ({total_w1_entries}銘柄分析)')
        return md

    except Exception as e:
        print(f'  [警告] 週次シナリオ精度レビュー失敗: {e}')
        return f'\n## 週次シナリオ精度レビュー（土曜）\n\n（レビュー生成失敗: {e}）\n'


def run_verification():
    """
    シミュレーション追跡 + 3シナリオ日次比較 + 他チームへのフィードバック (v2)
    - simulation_log.jsonを更新（最大5銘柄・20営業日・3シナリオ）
    - verification.mdを生成
    """
    sim_log_path = REPORT_DIR / 'simulation_log.json'
    log = {'tracking_rule': '1ヶ月(20営業日)追跡・最大5銘柄同時・3シナリオ', 'actives': [], 'history': []}
    # ローカルになければinvest-dataから読む（GitHub Actions環境対応）
    for _candidate in [sim_log_path, DATA_DIR / 'reports' / 'simulation_log.json']:
        if _candidate.exists():
            try:
                raw = json.loads(_candidate.read_text(encoding='utf-8'))
                # 旧フォーマット（active単体）からの移行
                if 'active' in raw and 'actives' not in raw:
                    old = raw.pop('active')
                    raw['actives'] = [old] if old else []
                log = raw
                break
            except Exception:
                pass
    # 常に最新のtracking_ruleに更新（旧JSONから読み込んだ場合でも上書き）
    log['tracking_rule'] = '1ヶ月(20営業日)追跡・最大5銘柄同時・3シナリオ'

    screen = load_json('screen_full_results.json', {})
    stocks = screen_to_list(screen)
    stocks_by_code = {str(s.get('code', '')): s for s in stocks if isinstance(s, dict)}

    analysis_report = read_report('analysis')
    strategy_report = read_report('strategy')
    history = log.get('history', [])
    actives = log.get('actives', [])

    # ── 機能1: 市場フェーズ取得（シナリオ確率補正用） ──
    market_phase = None
    try:
        market_phase = detect_phase(stocks)
        print(f'  [フェーズ判定] {market_phase["phase"]} (スコア: {market_phase["score"]})')
    except Exception as e:
        print(f'  [警告] フェーズ判定失敗: {e}')

    # ── 各アクティブシミュレーションの更新 ──
    completion_notes = []
    remaining = []
    hypothesis_checks = []  # 仮説検証結果ログ
    for sim in actives:
        code = str(sim.get('code', ''))

        # ── 重複実行ガード: 同日分のdaily_logがすでに存在する場合はスキップ ──
        if IS_MARKET_DAY and sim.get('daily_log'):
            last_log_date = sim['daily_log'][-1].get('date', '')
            if last_log_date == TODAY:
                print(f'  [スキップ] {sim.get("name", code)}: 本日分({TODAY})のdaily_log記録済み（重複防止）')
                remaining.append(sim)
                continue

        current_stock = stocks_by_code.get(code)
        prev_price = sim.get('current_price', sim.get('entry_price'))
        # screen_full_results.json のキャッシュ価格を取得後、J-Quantsで最新終値に上書き
        screen_price = current_stock.get('price', prev_price) if current_stock else prev_price
        current_price = _fetch_fresh_price(code, screen_price)
        if current_price != screen_price:
            print(f'  [価格更新] {sim.get("name", code)}: screen={screen_price} → J-Quants={current_price}')
        entry = sim['entry_price']
        stop = sim['stop_loss']
        target1 = sim['target1']

        days_elapsed = sim.get('days_elapsed', 0) + (1 if IS_MARKET_DAY else 0)
        sim['days_elapsed'] = days_elapsed
        sim['current_price'] = current_price
        pct = (current_price - entry) / entry * 100 if entry else 0
        sim['current_pct'] = round(pct, 2)

        # ── v2: 3シナリオ日次比較（平日のみ） ──
        if IS_MARKET_DAY and sim.get('scenarios'):
            scenarios = sim['scenarios']
            cumulative_pct = sim['current_pct']
            daily_pct_change = (current_price - prev_price) / prev_price * 100 if prev_price else 0

            leading = _determine_leading_scenario(scenarios, cumulative_pct, days_elapsed)
            gaps = _scenario_gaps(scenarios, cumulative_pct, days_elapsed)

            prev_hyp = sim.get('current_hypothesis') or {}
            daily_entry = {
                'date': TODAY,
                'price': current_price,
                'daily_pct': round(daily_pct_change, 2),
                'cumulative_pct': round(cumulative_pct, 2),
                'leading_scenario': leading,
                'scenario_gaps': gaps,
            }

            # Claude で差異分析 + 翌日仮説
            print(f'    [Claude] {sim["name"]} 差異分析中...')
            analysis = _analyze_daily_deviation(sim, daily_entry, prev_hyp)
            daily_entry['cause'] = analysis.get('cause', '')
            daily_entry['hypothesis_revision'] = analysis.get('hypothesis_revision', '修正なし')
            daily_entry['updated_probabilities'] = analysis.get('updated_probabilities', {sid: scenarios[sid].get('probability', 33) for sid in scenarios})
            daily_entry['prev_match'] = analysis.get('prev_match')  # 前日仮説的中フラグ（True/False/None）

            # シナリオ確率を更新
            updated_probs = analysis.get('updated_probabilities', {})
            for sid, prob in updated_probs.items():
                if sid in scenarios:
                    scenarios[sid]['probability'] = prob

            if 'daily_log' not in sim:
                sim['daily_log'] = []
            sim['daily_log'].append(daily_entry)

            # current_hypothesis 更新
            sim['current_hypothesis'] = {
                'date': TODAY,
                'leading_scenario': leading,
                'next_day_direction': analysis.get('next_day_direction', '横ばい'),
                'next_day_reason': analysis.get('next_day_reason', ''),
                'next_day_confidence': analysis.get('next_day_confidence', '中'),
                'next_day_key_level': analysis.get('next_day_key_level', ''),
            }

            prev_match = analysis.get('prev_match')
            match_str = '○' if prev_match else ('×' if prev_match is False else '-')
            hypothesis_checks.append(
                f"{sim['name']}: リード={leading} 前日仮説={match_str} {daily_pct_change:+.1f}%"
            )

        elif IS_MARKET_DAY and sim.get('next_hypothesis') and prev_price:
            # 旧フォーマット後方互換: next_hypothesis のみ持つ銘柄
            hyp = sim['next_hypothesis']
            actual_direction = '上昇' if current_price > prev_price else ('下落' if current_price < prev_price else '横ばい')
            hyp_direction = hyp.get('direction', '')
            match = (hyp_direction == '上昇' and current_price > prev_price) or \
                    (hyp_direction == '下落' and current_price < prev_price)
            price_change_pct = (current_price - prev_price) / prev_price * 100 if prev_price else 0
            result_entry = {
                'date': TODAY,
                'hypothesis_date': hyp.get('date', ''),
                'direction': hyp_direction,
                'reason': hyp.get('reason', ''),
                'confidence': hyp.get('confidence', ''),
                'actual_direction': actual_direction,
                'prev_price': prev_price,
                'actual_price': current_price,
                'price_change_pct': round(price_change_pct, 2),
                'match': match
            }
            if 'hypothesis_history' not in sim:
                sim['hypothesis_history'] = []
            sim['hypothesis_history'].append(result_entry)
            hypothesis_checks.append(
                f"{sim['name']}: 予測={hyp_direction} 実際={actual_direction} "
                f"({'○' if match else '×'}) {price_change_pct:+.1f}%"
            )
            sim['next_hypothesis'] = None

        ended = False
        if current_price <= stop:
            sim['result'] = 'stopped_out'
            sim['result_pct'] = round(pct, 2)
            completion_notes.append(f"{sim['name']}: 損切り到達 ({pct:+.1f}%)")
            ended = True
        elif current_price >= target1:
            sim['result'] = 'target1_hit'
            sim['result_pct'] = round(pct, 2)
            completion_notes.append(f"{sim['name']}: 目標①到達 ({pct:+.1f}%)")
            ended = True
        elif days_elapsed >= 20:
            sim['result'] = 'time_expired'
            sim['result_pct'] = round(pct, 2)
            completion_notes.append(f"{sim['name']}: 期間終了 ({pct:+.1f}%)")
            ended = True

        if ended:
            sim['end_date'] = TODAY
            sim['direction_match'] = (entry < target1) == (current_price > entry)
            history.append(sim)
        else:
            remaining.append(sim)

    actives = remaining
    log['history'] = history

    # ── シナリオ未生成の既存アクティブに3シナリオを追加（市場開閉問わず実行） ──
    # シナリオ生成は市場データ不要（エントリー価格・RSスコアのみ使用）
    sims_without_scenarios = [s for s in actives if not s.get('scenarios')]
    if sims_without_scenarios:
        print(f'  [Claude] 既存銘柄{len(sims_without_scenarios)}件のシナリオ生成中...')
        for sim in sims_without_scenarios:
            # 機能1: market_phaseを渡してフェーズ考慮のシナリオ確率を生成
            sim['scenarios'] = _generate_scenarios(sim, analysis_report[:500], market_phase=market_phase)
            print(f'    -> {sim["name"]} シナリオ生成完了')

    # ── 空きスロットを埋める（平日のみ） ──
    new_sim_notes = []
    if IS_MARKET_DAY and len(actives) < MAX_SIM_SLOTS:
        a_rank_stocks = sorted(
            [s for s in stocks if isinstance(s, dict) and _score_num(s) >= 6],
            key=_rs26w, reverse=True
        )
        # 直近30日のhistory + 現在actives で使用済みコードを除外
        used_codes = {str(h.get('code', '')) for h in history if h.get('start_date', '') >= (
            __import__('datetime').date.today() - __import__('datetime').timedelta(days=30)
        ).isoformat()}
        used_codes |= {str(a.get('code', '')) for a in actives}
        candidates = [s for s in a_rank_stocks if str(s.get('code', '')) not in used_codes]

        slots_to_fill = MAX_SIM_SLOTS - len(actives)
        filled = 0
        for best in candidates:
            if filled >= slots_to_fill:
                break
            candidate_code = str(best.get('code', ''))
            # 機能2: セクター分散チェック
            try:
                sector_ok, sector_reason = _check_sector_diversity(actives, candidate_code, stocks_by_code)
                if not sector_ok:
                    print(f'  [セクター分散] スキップ: {best.get("name","")}({candidate_code}) - {sector_reason}')
                    continue
                print(f'  [セクター分散] 追加可能: {best.get("name","")}({candidate_code}) - {sector_reason}')
            except Exception as e:
                print(f'  [警告] セクター分散チェックエラー: {e} → 追加を許可')

            new_sim = _make_new_sim(best)
            # 機能1: market_phaseを渡してフェーズ考慮のシナリオ確率を生成
            print(f'  [Claude] {best.get("name","")} のシナリオ生成中...')
            new_sim['scenarios'] = _generate_scenarios(new_sim, analysis_report[:500], market_phase=market_phase)
            actives.append(new_sim)
            new_sim_notes.append(f"新規: {best.get('name','')}({best.get('code','')}) EP={best.get('price',0):.0f}円")
            filled += 1

    log['actives'] = actives
    log['last_updated'] = TODAY
    sim_log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  -> simulation_log.json 更新 (追跡中: {len(actives)}件)')

    # ── 統計計算 ──
    completed = [h for h in history if h.get('result')]
    wins = [h for h in completed if h.get('result_pct', 0) > 0]
    win_rate = len(wins) / len(completed) * 100 if completed else 0
    avg_win = sum(h.get('result_pct', 0) for h in wins) / len(wins) if wins else 0
    losses = [h for h in completed if h.get('result_pct', 0) <= 0]
    avg_loss = sum(h.get('result_pct', 0) for h in losses) / len(losses) if losses else 0
    direction_matches = [h for h in completed if h.get('direction_match')]
    dir_accuracy = len(direction_matches) / len(completed) * 100 if completed else 0

    # ── 機能3: 土曜日 週次シナリオ精度レビュー ──
    weekly_review_md = ''
    if DAY_MODE == 'saturday':
        print(f'  [土曜] 週次シナリオ精度レビュー実行...')
        try:
            weekly_review_md = _weekly_scenario_review(actives, history)
            print(f'  [土曜] 週次レビュー生成完了')
        except Exception as e:
            print(f'  [警告] 週次レビュー生成失敗: {e}')
            weekly_review_md = f'\n## 週次シナリオ精度レビュー（土曜）\n\n（レビュー生成失敗: {e}）\n'

    # ── Gemini: 精度向上のための情報収集 ──
    print(f'  [Gemini] 検証情報収集中... ({DAY_LABEL})')
    active_names = ', '.join(a['name'] for a in actives) if actives else 'なし'
    hyp_check_str = '\n'.join(hypothesis_checks) if hypothesis_checks else 'なし（週末または仮説未設定）'
    # v2: 仮説精度計算 — daily_log.prev_match 優先、旧hypothesis_historyにフォールバック
    all_daily = [d for a in (actives + history) for d in a.get('daily_log', [])]
    dlog_with_match = [d for d in all_daily if d.get('prev_match') is not None]
    if dlog_with_match:
        hyp_hits = sum(1 for d in dlog_with_match if d.get('prev_match') is True)
        hyp_total = len(dlog_with_match)  # 機能4: hyp_total を定義（バグ修正）
        hyp_accuracy = hyp_hits / hyp_total * 100
    else:
        # 旧フォーマット後方互換
        all_hyp_old = [h for a in (actives + history) for h in a.get('hypothesis_history', [])]
        hyp_hits = sum(1 for h in all_hyp_old if h.get('match'))
        hyp_total = len(all_hyp_old)  # 機能4: hyp_total を定義（バグ修正）
        hyp_accuracy = hyp_hits / hyp_total * 100 if hyp_total else 0

    # ── 機能4: v2精度KPI計算（シナリオ的中率） ──
    scenario_accuracy = {}
    match_entries_count = 0  # 機能4: スコープ外参照を安全化
    try:
        dlog_all = [d for a in actives + history for d in a.get('daily_log', [])]
        match_entries = [d for d in dlog_all if d.get('prev_match') is not None]
        match_entries_count = len(match_entries)
        hyp_accuracy_v2 = (
            sum(1 for d in match_entries if d['prev_match']) / match_entries_count * 100
            if match_entries else None
        )
        # シナリオ的中率: 各シナリオがリードしていた日の比率
        for sid in ('bull', 'base', 'bear'):
            lead_entries = [d for d in dlog_all if d.get('leading_scenario') == sid]
            if lead_entries:
                # リードシナリオ当日に、そのシナリオの方向（pct符号）と一致したか
                sid_sign = 1 if sid == 'bull' else (-1 if sid == 'bear' else 0)
                if sid == 'base':
                    # base: 騰落率が-2%〜+2%の範囲（横ばい）
                    correct = sum(1 for d in lead_entries if abs(d.get('daily_pct', 0)) <= 2.0)
                else:
                    correct = sum(
                        1 for d in lead_entries
                        if (d.get('daily_pct', 0) * sid_sign) > 0
                    )
                scenario_accuracy[sid] = round(correct / len(lead_entries) * 100, 1)
            else:
                scenario_accuracy[sid] = None
        print(f'  [KPI v2] 仮説的中率v2={hyp_accuracy_v2:.1f}% ({len(match_entries)}件)' if hyp_accuracy_v2 is not None else '  [KPI v2] 仮説的中率v2: データなし')
        print(f'  [KPI v2] シナリオ的中率: bull={scenario_accuracy.get("bull")}% base={scenario_accuracy.get("base")}% bear={scenario_accuracy.get("bear")}%')
    except Exception as e:
        print(f'  [警告] v2精度KPI計算失敗: {e}')
        hyp_accuracy_v2 = None
        scenario_accuracy = {'bull': None, 'base': None, 'bear': None}

    # シナリオ的中率の文字列化（プロンプト用）
    def _fmt_accuracy(val):
        return f'{val:.1f}%' if val is not None else 'データなし'

    scenario_accuracy_str = (
        f"bull(強気)={_fmt_accuracy(scenario_accuracy.get('bull'))} / "
        f"base(中立)={_fmt_accuracy(scenario_accuracy.get('base'))} / "
        f"bear(弱気)={_fmt_accuracy(scenario_accuracy.get('bear'))}"
    )
    hyp_accuracy_v2_str = (
        f'{hyp_accuracy_v2:.1f}% ({match_entries_count}件)'
        if hyp_accuracy_v2 is not None else 'データなし'
    )

    sim_summary = f"追跡中({len(actives)}件): {active_names} / 累計{len(completed)}件完了 / 勝率{win_rate:.0f}% / 日次ログ{len(all_daily)}件 / 仮説的中率{hyp_accuracy:.0f}%({hyp_total}件)"
    g_prompt = f"""投資シミュレーションの精度向上に役立つ情報を収集してください。

現在の状況: {sim_summary}

1. ミネルヴィニ戦略における損切り-8%・目標+25%・1ヶ月追跡の有効性に関する研究・事例
2. 日本株でのモメンタム投資の勝率・期待値に関する統計データ
3. RS（相対強度）指標の精度を高めるための改善手法
4. 強気・中立・弱気の3シナリオ分析が投資判断に与える効果（行動ファイナンス観点）
5. 機械学習・AIを使った株価シナリオ予測精度の現状（参考として）
"""
    gemini_text, sources = call_gemini(g_prompt)
    save_source_log('シミュレーション追跡・検証チーム', sources, gemini_text)

    # ── Claude: 検証レポート生成 ──
    history_str = json.dumps(history[-10:], ensure_ascii=False, indent=2) if history else '（履歴なし）'
    actives_str = json.dumps(actives, ensure_ascii=False, indent=2) if actives else '（なし）'

    # アクティブ追跡テーブル行生成
    active_table_rows = ''
    for a in actives:
        # v2: リードシナリオを表示（current_hypothesisから取得）
        leading_label = ''
        hyp = a.get('current_hypothesis') or {}
        if hyp.get('leading_scenario'):
            sid = hyp['leading_scenario']
            scen = (a.get('scenarios') or {}).get(sid, {})
            leading_label = f" [{scen.get('label', sid)}]"
        active_table_rows += f"| {a['name']}（{a['code']}） | {a['entry_price']}円 | {a['current_price']}円（{a['current_pct']:+.1f}%）{leading_label} | {a['stop_loss']}円 | {a['target1']}円 | {a['days_elapsed']}/20日 |\n"
    if not active_table_rows:
        active_table_rows = "| （なし） | - | - | - | - | - |\n"

    prompt = f"""あなたは投資チームの「シミュレーション追跡・検証チーム」です。{DAY_LABEL}の検証レポートを作成してください。

## アクティブシミュレーション（{len(actives)}件）
{actives_str}

## 本日の更新
- 完了: {', '.join(completion_notes) if completion_notes else 'なし'}
- 新規開始: {', '.join(new_sim_notes) if new_sim_notes else 'なし'}

## 翌日仮説の検証結果（本日）
{hyp_check_str}

## シミュレーション履歴（直近10件）
{history_str}

## 累計統計
- 完了件数: {len(completed)}件
- 勝率: {win_rate:.1f}%（目標: 50%→60%）
- 平均利益: {avg_win:+.1f}%
- 平均損失: {avg_loss:+.1f}%
- 方向一致率: {dir_accuracy:.1f}%
- 翌日仮説的中率: {hyp_accuracy:.1f}%（{hyp_hits}/{hyp_total}件）
- 仮説的中率v2（daily_log集計）: {hyp_accuracy_v2_str}
- シナリオ別的中率: {scenario_accuracy_str}

## 銘柄選定・仮説チームレポート（参照）
{analysis_report[:800]}

## 投資戦略チームレポート（参照）
{strategy_report[:600]}

## Geminiが収集した精度向上のための情報
{gemini_text}

## 出力フォーマット（必ずこの形式で）
# シミュレーション追跡・検証チーム レポート [{DAY_LABEL}]
日付: {TODAY}

## シミュレーション現況
### アクティブ追跡（最大{MAX_SIM_SLOTS}銘柄同時）
| 銘柄 | エントリー | 現在値 | 損切り | 目標① | 経過 |
|------|-----------|--------|--------|--------|------|
{active_table_rows}
## 累計パフォーマンス
| KPI | 現状 | 目標 | 評価 |
|-----|------|------|------|
| 完了件数 | {len(completed)}件 | 積み上げ中 | - |
| 勝率 | {win_rate:.1f}% | 50%以上 | {'✅' if win_rate >= 50 else '⚠️' if completed else '-'} |
| 方向一致率 | {dir_accuracy:.1f}% | 50%→60% | {'✅' if dir_accuracy >= 50 else '⚠️' if completed else '-'} |
| 平均利益 | {avg_win:+.1f}% | +25%以上 | {'✅' if avg_win >= 25 else '⚠️' if wins else '-'} |
| 平均損失 | {avg_loss:+.1f}% | -8%以内 | {'✅' if avg_loss >= -8 else '⚠️' if losses else '-'} |
| 日次ログ累計 | {len(all_daily)}件 | 積み上げ中 | - |
| 仮説的中率（v2） | {hyp_accuracy_v2_str} | 50%以上 | {'✅' if (hyp_accuracy_v2 or 0) >= 50 else '⚠️' if hyp_accuracy_v2 is not None else '-'} |

## 仮説・シナリオ精度KPI（v2）
| 指標 | 結果 | 件数 |
|------|------|------|
| 仮説的中率（翌日方向） | {hyp_accuracy_v2_str} | {len(dlog_all)}件(全日次ログ) |
| 強気(bull)シナリオ日次精度 | {_fmt_accuracy(scenario_accuracy.get('bull'))} | - |
| 中立(base)シナリオ日次精度 | {_fmt_accuracy(scenario_accuracy.get('base'))} | - |
| 弱気(bear)シナリオ日次精度 | {_fmt_accuracy(scenario_accuracy.get('bear'))} | - |
（シナリオ日次精度: リードシナリオ当日の値動きがそのシナリオ方向と一致した割合）

## 3シナリオ日次追跡（本日の差異分析）
担当: **シミュレーション追跡・検証チーム**
（本日の3シナリオ分析: {hyp_check_str}）
（各銘柄の「リードシナリオ」と実際の値動きの乖離を分析。シナリオ確率の更新根拠を明記）

## 翌日方向仮説（各銘柄のcurrent_hypothesisに記録済み）
（各銘柄の次営業日方向・根拠・信頼度・注目価格水準を補足説明）

## 直近の結果振り返り
担当: **シミュレーション追跡・検証チーム**
（直近3件の売買結果: どのシナリオが最終的に優位だったか、3シナリオ設計の精度を評価）

## 分析精度の改善提案
### → 銘柄選定・仮説チームへ（担当: シミュレーション追跡・検証チーム →銘柄選定・仮説チーム）
（Aランク選定基準・シナリオ設計の改善点）

### → 投資戦略チームへ（担当: シミュレーション追跡・検証チーム →投資戦略チーム）
（エントリータイミング・損切り設定・シナリオ移行ルールの改善点）

## 学習パターン
担当: **シミュレーション追跡・検証チーム**
（蓄積データから見えてきた傾向・どのシナリオが的中しやすいか等の法則）

## 参考: 精度向上のためのベストプラクティス
（Gemini情報より）
"""
    verification_content = call_claude(prompt, max_tokens=5000)

    # 機能3: 土曜日の場合は週次シナリオ精度レビューを末尾に追記
    if DAY_MODE == 'saturday' and weekly_review_md:
        verification_content += '\n' + weekly_review_md

    write_report('verification', verification_content)

    # 検証チームの知識を蓄積（将来の選定精度向上のため）
    if IS_MARKET_DAY and (hypothesis_checks or completion_notes):
        knowledge_entry = f"""### 本日の検証サマリー
- フェーズ: {market_phase.get('phase', '不明') if market_phase else '不明'}
- 仮説確認: {'; '.join(hypothesis_checks) if hypothesis_checks else 'なし'}
- 完了: {'; '.join(completion_notes) if completion_notes else 'なし'}
- 新規追跡: {'; '.join(new_sim_notes) if new_sim_notes else 'なし'}
- 累計勝率: {win_rate:.1f}% ({len(wins)}/{len(completed)})"""
        write_knowledge('verification_patterns', knowledge_entry)


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

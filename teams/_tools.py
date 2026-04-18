"""エージェントツール infrastructure: ツール定義・ツール実行・エージェントループ。

各チーム (`run_info_gathering` 等) はこの `_run_agent_team()` を介して Claude の
tool_use ループで自律的にツールを呼び出す。
"""
from __future__ import annotations

import json
import os
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



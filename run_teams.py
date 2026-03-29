#!/usr/bin/env python3
"""
Investment Team System - GitHub Actions runner
各チームがClaude/Gemini APIを呼び出してレポートを生成する
"""
import anthropic
import json
import os
import sys
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
NOW_JST = datetime.now(JST)
TODAY = NOW_JST.strftime('%Y-%m-%d')
WEEKDAY = NOW_JST.weekday()  # 0=月 … 4=金, 5=土, 6=日
IS_MARKET_DAY = WEEKDAY < 5

# 曜日別モード: 各チームのプロンプトで参照する
if WEEKDAY < 5:
    DAY_MODE = 'weekday'
    DAY_LABEL = f'平日（市場稼働日: {TODAY}）'
    DAY_FOCUS = '本日の市場データ取得・銘柄分析・アクションプラン策定'
elif WEEKDAY == 5:
    DAY_MODE = 'saturday'
    DAY_LABEL = f'土曜日（週次振り返り: {TODAY}）'
    DAY_FOCUS = '今週の業績振り返り・KPI評価・分析精度の改善点整理'
else:
    DAY_MODE = 'sunday'
    DAY_LABEL = f'日曜日（翌週準備: {TODAY}）'
    DAY_FOCUS = '翌週の戦略立案・注目銘柄の事前分析・リスクシナリオ整理'

DATA_DIR = Path(os.environ.get('INVEST_DATA_DIR', 'invest-data'))
REPORT_DIR = Path('reports') / 'daily'
REPORT_DIR.mkdir(parents=True, exist_ok=True)

client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
MODEL = 'claude-sonnet-4-6'
GEMINI_KEY = os.environ.get('GEMINI_API', '')
GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'

# ─── チーム別KPI定義（全チーム共通の評価基準） ────────────────────
TEAM_KPIS = {
    '情報収集チーム': {
        'description': '市場情報を正確・迅速に収集し、後続チームに届ける',
        'kpis': [
            {'id': 'info_coverage',    'what': '必須8項目の網羅率',         'target': '100%',     'how': '指数/為替/債券/コモディティ/イベント/セクター/ニュース/RS上位が全て記載されているか'},
            {'id': 'info_accuracy',    'what': 'データ誤り件数',             'target': '0件/日',   'how': 'スクリーニング数値と実際のGemini取得値が整合しているか'},
            {'id': 'source_quality',   'what': '信頼度4以上ソース比率',      'target': '70%以上',  'how': 'source_log.md の reliability≥4 件数 / 全件数'},
            {'id': 'source_count',     'what': '情報源数',                   'target': '3件以上',  'how': 'Gemini groundingChunks の件数'},
        ]
    },
    '銘柄選定・仮説チーム': {
        'description': 'Aランク銘柄を正確に選定し、判断理由を明示する',
        'kpis': [
            {'id': 'a_rank_win_rate',  'what': 'Aランク銘柄の2週間後勝率',  'target': '60%以上',  'how': 'シミュレーション追跡・検証チームがシミュレーションで追跡・集計'},
            {'id': 'rs_retention',     'what': 'Aランク選定銘柄のRS維持率', 'target': '70%以上',  'how': '2週後もRS26w上位30%以内を維持している割合'},
            {'id': 'reason_quality',   'what': '判断理由の具体性',           'target': '根拠3つ以上/銘柄', 'how': 'テクニカル/ファンダ/RS の3軸で根拠が記載されているか'},
            {'id': 'stock_count',      'what': '評価銘柄数',                 'target': '5銘柄以上/日', 'how': 'A/B/Cランク合計の評価銘柄数'},
        ]
    },
    'リスク管理チーム': {
        'description': '資産を守り、ルールベースのリスク管理を徹底する',
        'kpis': [
            {'id': 'dd_compliance',    'what': 'DD許容上限遵守',             'target': '-10%以内', 'how': 'ポートフォリオ全体のドローダウンが-20万円を超えていないか'},
            {'id': 'stoploss_coverage','what': '損切りライン設定率',          'target': '保有全銘柄100%', 'how': '各保有銘柄に損切り価格が設定・記載されているか'},
            {'id': 'sector_limit',     'what': 'セクター集中度',             'target': '30%以内',  'how': '最大セクターの資産占有率が30%を超えていないか'},
            {'id': 'alert_accuracy',   'what': '警告的中率（累積）',         'target': '60%以上',  'how': '過去の警告銘柄が実際に下落した割合（kpi_log.jsonで追跡）'},
        ]
    },
    '投資戦略チーム': {
        'description': '市場フェーズを正確に判定し、具体的なエントリー計画を立案する',
        'kpis': [
            {'id': 'phase_accuracy',   'what': 'フェーズ判定精度',           'target': '70%以上',  'how': '翌週の市場動向と当日判定（Attack/Steady/Defend）が一致した割合'},
            {'id': 'entry_win_rate',   'what': 'エントリー後2週間勝率',      'target': '50%以上',  'how': 'シミュレーション追跡・検証チームが追跡。エントリー推奨銘柄が2週後に利益圏にある割合'},
            {'id': 'rr_ratio',         'what': '平均RR比',                   'target': '3.0以上',  'how': '各エントリー候補の（目標-エントリー）/（エントリー-損切り）の平均'},
            {'id': 'plan_concreteness','what': 'アクションプランの具体性',   'target': '銘柄/価格/理由を全て明記', 'how': 'エントリー候補テーブルに銘柄名・コード・価格・損切り・目標・RR比・根拠が記載されているか'},
        ]
    },
    'レポート統括': {
        'description': '全チーム情報を統合し、読みやすい日次レポートを作成する',
        'kpis': [
            {'id': 'integration_rate', 'what': '全チームレポート統合率',     'target': '100%',     'how': '情報収集/分析/リスク/戦略の4チームの内容が全て含まれているか'},
            {'id': 'next_day_points',  'what': '翌日注目点の明記',           'target': '必須3件以上', 'how': '「来週以降の注目点」または「翌日の注目点」セクションに3件以上あるか'},
            {'id': 'fact_ai_label',    'what': '[事実]/[AI分析]ラベル遵守', 'target': '100%',     'how': 'レポート内の全セクションに[事実]または[AI分析]ラベルが付いているか'},
        ]
    },
    'セキュリティチーム': {
        'description': 'コードとシステムの安全性を監視し、脅威を早期検知する',
        'kpis': [
            {'id': 'critical_zero',    'what': '重大脆弱性の未報告ゼロ',     'target': '0件',      'how': 'CRITICAL/HIGH相当の脆弱性が発見された場合、必ず報告されているか'},
            {'id': 'code_review',      'what': 'コードレビュー実施',         'target': '週1回以上', 'how': '直近7日間でrun_teams.py/index.htmlのレビューを実施したか'},
            {'id': 'threat_freshness', 'what': '脅威情報の鮮度',             'target': '当日情報を含む', 'how': 'Geminiが収集した脅威情報に当日（{TODAY}）の日付が含まれているか'},
        ]
    },
    '内部監査チーム': {
        'description': '全チームのKPI達成状況を評価し、改善サイクルを推進する',
        'kpis': [
            {'id': 'audit_coverage',   'what': '全チーム評価完了率',         'target': '100%',     'how': '全チームに対して評価スコアが付いているか'},
            {'id': 'improvement_count','what': '改善提案数',                 'target': '2件以上/日', 'how': '優先度「高」または「中」の改善提案が合計2件以上あるか'},
            {'id': 'followup_rate',    'what': '前回提案フォローアップ率',   'target': '100%',     'how': '前回の改善提案に対して今回の評価で言及しているか'},
            {'id': 'pdca_cycle',       'what': 'PDCA回転数',                 'target': '週4回以上', 'how': '過去7日間でaudit_log.mdへの書き込みが4回以上あるか'},
        ]
    },
    'シミュレーション追跡・検証チーム': {
        'description': 'シミュレーション追跡と差異分析により、全チームの予測精度を向上させる',
        'kpis': [
            {'id': 'sim_direction',    'what': 'シミュレーション方向一致率', 'target': '50%→60%（成長目標）', 'how': '予測した上昇/下落方向と実際の結果が一致した割合'},
            {'id': 'analysis_complete','what': '差異分析完了率',             'target': '100%',     'how': '追跡終了した全シミュレーションに原因分析が付いているか'},
            {'id': 'kpi_check',        'what': 'KPI自動チェック実施',        'target': '毎日',     'how': 'kpi_log.jsonに当日分の記録があるか'},
            {'id': 'feedback_count',   'what': '他チームへのフィードバック数', 'target': '1件以上/週', 'how': '銘柄選定・仮説チーム・投資戦略チームへの改善フィードバックが週1件以上あるか'},
        ]
    },
}

# 信頼性スコア定義（ドメインベース）
SOURCE_RELIABILITY = {
    'nikkei.com': ('日経新聞', 5), 'reuters.com': ('Reuters', 5),
    'bloomberg.com': ('Bloomberg', 5), 'wsj.com': ('WSJ', 5),
    'minkabu.jp': ('みんかぶ', 4), 'kabutan.jp': ('株探', 4),
    'finance.yahoo.co.jp': ('Yahoo!ファイナンス', 4),
    'investing.com': ('Investing.com', 4), 'tradingview.com': ('TradingView', 4),
    'oanda.jp': ('OANDA', 3), 'diamond.jp': ('ダイヤモンド', 4),
}


def call_claude(prompt: str, max_tokens: int = 4096) -> str:
    msg = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}]
    )
    return msg.content[0].text


def call_gemini(prompt: str) -> tuple[str, list[dict]]:
    """Gemini with Google Search grounding。(text, sources) を返す"""
    if not GEMINI_KEY:
        return '（Gemini APIキー未設定）', []
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'tools': [{'google_search': {}}],
    }
    resp = requests.post(f'{GEMINI_URL}?key={GEMINI_KEY}', json=payload, timeout=60)
    data = resp.json()
    candidate = (data.get('candidates') or [{}])[0]
    text = (candidate.get('content', {}).get('parts') or [{}])[0].get('text', '')
    # grounding sources
    sources = []
    for chunk in candidate.get('groundingMetadata', {}).get('groundingChunks', []):
        web = chunk.get('web', {})
        uri = web.get('uri', '')
        title = web.get('title', uri)
        if uri:
            domain = uri.split('/')[2] if uri.startswith('http') else uri
            rel_name, rel_score = SOURCE_RELIABILITY.get(domain, ('その他', 3))
            sources.append({'title': title, 'url': uri, 'source': rel_name, 'reliability': rel_score})
    return text, sources


def save_source_log(team: str, sources: list[dict], raw_text: str = ''):
    """情報源ログを reports/source_log.md に追記（レポートには含まない）"""
    log_path = REPORT_DIR / 'source_log.md'
    existing = log_path.read_text(encoding='utf-8') if log_path.exists() else f'# 情報源ログ\n'
    lines = [f'\n## {TODAY} - {team}']
    if sources:
        lines.append('| 情報源 | 信頼性 | URL |')
        lines.append('|--------|--------|-----|')
        for s in sources:
            stars = '★' * s['reliability'] + '☆' * (5 - s['reliability'])
            short_url = s['url'][:60] + '...' if len(s['url']) > 60 else s['url']
            lines.append(f"| {s['title'][:30]} ({s['source']}) | {stars} | {short_url} |")
    else:
        lines.append('（情報源なし）')
    log_path.write_text(existing + '\n'.join(lines) + '\n', encoding='utf-8')
    print(f'  -> source_log.md 更新 ({len(sources)}件)')


def load_json(filename: str, default=None):
    path = DATA_DIR / filename
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            pass
    return default if default is not None else {}


def read_report(name: str) -> str:
    path = REPORT_DIR / f'{name}.md'
    return path.read_text(encoding='utf-8') if path.exists() else '（未生成）'


def write_report(name: str, content: str):
    path = REPORT_DIR / f'{name}.md'
    path.write_text(content, encoding='utf-8')
    print(f'  -> {path}')


def save_kpi_log(kpi_results: dict):
    """KPI達成状況を kpi_log.json に追記（日次トレンド分析用）"""
    log_path = REPORT_DIR / 'kpi_log.json'
    existing = []
    if log_path.exists():
        try:
            existing = json.loads(log_path.read_text(encoding='utf-8'))
        except Exception:
            pass
    # 当日分を上書き or 追加
    existing = [e for e in existing if e.get('date') != TODAY]
    existing.append({'date': TODAY, 'teams': kpi_results})
    # 直近3年分（1095日）保持 — 投資目標の3年ロードマップ全体を記録
    existing = existing[-1095:]
    log_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  -> kpi_log.json 更新')


def build_kpi_check_prompt() -> str:
    """内部監査用: 全チームKPI一覧をテキストに変換"""
    lines = ['## 各チームのKPI定義']
    for team, info in TEAM_KPIS.items():
        lines.append(f'\n### {team}')
        lines.append(f'ミッション: {info["description"]}')
        lines.append('| ID | 何を測る | 目標値 | 評価方法 |')
        lines.append('|----|---------|--------|---------|')
        for k in info['kpis']:
            lines.append(f'| {k["id"]} | {k["what"]} | {k["target"]} | {k["how"]} |')
    return '\n'.join(lines)


# ─── Team 1: 情報収集 ────────────────────────────────────────────
def run_info_gathering():
    screen = load_json('screen_full_results.json', [])
    stocks = screen if isinstance(screen, list) else []
    total = len(stocks)
    top = sorted(
        [s for s in stocks if isinstance(s, dict)],
        key=lambda x: x.get('rs_26w', 0), reverse=True
    )[:10]
    top_str = '\n'.join(
        f"  {s.get('code','?')} {s.get('name','')}: RS26w={s.get('rs_26w','?')}, score={s.get('score','?')}"
        for s in top
    )

    print(f'  [Gemini] 情報収集中... ({DAY_LABEL})')
    if IS_MARKET_DAY:
        g_prompt = f"""{TODAY} の最新市場情報を収集してください。

以下を正確な数値で答えてください（最新の終値・速報値）:
1. 日経平均・TOPIX・マザーズ の終値と前日比（%）
2. S&P500・NASDAQ・ダウ の終値と前日比（%）
3. ドル円・ユーロ円 の現在値
4. 米10年債利回り・日本10年債利回り
5. WTI原油・金 の現在値
6. 本日〜今週の重要経済イベント（日時・内容・予想値）
7. 昨日のS&P500セクター別騰落ランキング（全11セクター）
8. 日本株・米国株で昨日特に話題になったニュース3件
9. 直近3営業日以内に提出された大量保有報告書（5%超取得）の主要事例（銘柄名・提出者・保有割合・目的）
10. 本日の日本株で出来高急増（前日比2倍以上）した銘柄トップ5（銘柄名・出来高比率・急増理由）
"""
    elif DAY_MODE == 'saturday':
        g_prompt = f"""今週（{TODAY}週）の市場総括と来週の展望を収集してください。

1. 今週の日経平均・S&P500・NASDAQの週間騰落率と主要テーマ
2. 今週最も動いたセクター（上位3・下位3）とその理由
3. 来週（月〜金）の重要経済指標スケジュール（日時・予想値・注目理由）
4. 来週の日米主要決算発表予定
5. 今週の地政学・マクロ動向で来週に持ち越されるリスク
6. 機関投資家の今週の資金フロー動向（何が買われ何が売られたか）
"""
    else:  # sunday
        g_prompt = f"""来週（{TODAY}翌週）の投資環境を整理してください。

1. 来週の重要経済指標（日時・前回値・予想値・注目度）
2. 来週の日米主要決算（企業名・予想EPS・注目ポイント）
3. 来週のFRB高官発言・金融政策イベント予定
4. 来週注目のIPO・PO（需給への影響）
5. 来週のマクロ環境予測（強気・弱気シナリオ）
6. 週末の米国先物・ADR動向（日本市場への影響）
"""
    gemini_text, sources = call_gemini(g_prompt)
    save_source_log('情報収集チーム', sources, gemini_text)

    if IS_MARKET_DAY:
        output_format = f"""## 出力フォーマット（必ずこの形式で）
# 情報収集チーム レポート [{DAY_LABEL}]
日付: {TODAY}

## 市場概況
（表形式: 指数・終値・前日比）

## 為替・コモディティ
| 項目 | 現在値 | 動向 |
...

## 金利
| 項目 | 水準 | 動向 |
...

## 本日の注目イベント
（日時・内容・予想値・注目理由）

## セクター動向（S&P500）
（上昇・下落ランキング）

## 注目ニュース
1. ...
2. ...
3. ...

## 大量保有報告書（直近3営業日）
| 銘柄 | 提出者 | 保有割合 | 目的 |
...
（情報がない場合は「本日提出なし」と記載）

## 出来高急増銘柄（前日比2倍以上）
| 銘柄 | 出来高比率 | 急増理由 |
...
（情報がない場合は「該当なし」と記載）

## スクリーニング状況
スキャン: {total}銘柄 / RS上位10銘柄
{top_str}"""
    elif DAY_MODE == 'saturday':
        output_format = f"""## 出力フォーマット（必ずこの形式で）
# 情報収集チーム レポート [{DAY_LABEL}]
日付: {TODAY}

## 今週の市場総括
| 指数 | 今週騰落 | 主要テーマ |
...

## 今週のセクター動向
（上位3・下位3とその理由）

## 来週の重要イベントカレンダー
| 日付 | イベント | 予想値 | 注目理由 |
...

## 来週の決算スケジュール
（注目企業名・予想EPS）

## 持ち越しリスク
（来週に影響する今週の懸念事項）"""
    else:
        output_format = f"""## 出力フォーマット（必ずこの形式で）
# 情報収集チーム レポート [{DAY_LABEL}]
日付: {TODAY}

## 来週の重要イベントカレンダー（詳細版）
| 曜日 | 日時 | イベント | 前回値 | 予想値 | 注目度 |
...

## 来週の決算カレンダー
| 曜日 | 企業 | 予想EPS | 注目ポイント |
...

## マクロ環境シナリオ
### 強気シナリオ（買い場出現の条件）
### 弱気シナリオ（リスクオフ継続の条件）

## 週明け日本市場への影響
（米先物・ADR動向より）"""

    prompt = f"""あなたは投資チームの「情報収集チーム」です。{DAY_LABEL}のレポートを作成してください。

## Geminiが収集した情報
{gemini_text}

{output_format}
"""
    write_report('info_gathering', call_claude(prompt))


# ─── Team 2: 分析 ────────────────────────────────────────────────
def run_analysis():
    screen = load_json('screen_full_results.json', [])
    stocks = screen if isinstance(screen, list) else []
    top20 = sorted(
        [s for s in stocks if isinstance(s, dict) and s.get('score', 0) >= 6],
        key=lambda x: x.get('rs_26w', 0), reverse=True
    )[:20]
    info_report = read_report('info_gathering')
    top10_names = [f"{s.get('code')} {s.get('name','')}" for s in top20[:10]]
    names_str = '・'.join(top10_names) if top10_names else '（データなし）'
    watchlist = load_json('watchlist.json', [])
    wl_names = '・'.join([f"{w.get('code','')} {w.get('name','')}" for w in watchlist[:10]]) if watchlist else '（なし）'

    print(f'  [Gemini] 銘柄情報収集中... ({DAY_LABEL})')
    if IS_MARKET_DAY:
        g_prompt = f"""以下の日本株について最新情報を収集してください。

対象銘柄: {names_str}

各銘柄について:
1. 直近の決算結果（売上・営業利益の前年比成長率）
2. 直近のニュース・材料（ポジティブ/ネガティブ）
3. アナリストの評価・目標株価
4. 株価の最近の動き（上昇トレンド中か、調整中か）
5. 業界全体の動向（追い風・逆風）
6. 直近の出来高動向（急増・急減のタイミングと要因、機関投資家の動きが示唆される異常出来高）

事実のみを記載し、情報が見つからない場合はその旨を明記してください。
"""
    elif DAY_MODE == 'saturday':
        g_prompt = f"""今週の株式市場を振り返り、分析精度の検証に必要な情報を収集してください。

監視銘柄: {wl_names}

1. 今週のRS上位銘柄の値動き実績（上昇・下落・レンジ）
2. 今週ブレイクアウトした銘柄とその継続性
3. 今週のミネルヴィニ戦略に合致した動き（Stage-2維持・崩壊）
4. セクター別の今週の強弱（勝ちセクター・負けセクター）
5. 来週のRS上位候補になりそうな銘柄・テーマ
"""
    else:  # sunday
        g_prompt = f"""来週エントリーを検討すべき日本株候補の事前情報を収集してください。

現在の監視銘柄: {wl_names}

1. 各監視銘柄の最新ファンダメンタルズ（直近決算・成長率）
2. 来週の各銘柄に関する決算・材料・イベント予定
3. セクターテーマ別の来週の有望銘柄
4. 新規に監視リスト入りを検討すべき急成長株（IPO含む）
5. ミネルヴィニ基準を満たしつつある「準備中」の銘柄
"""
    gemini_text, sources = call_gemini(g_prompt)
    save_source_log('銘柄選定・仮説チーム', sources, gemini_text)

    # vol_ratio summary for top20
    vol_highlights = [
        f"{s.get('code')} {s.get('name','')} (vol_ratio={s.get('vol_ratio',0):.2f})"
        for s in top20 if s.get('vol_ratio', 0) >= 1.5
    ]
    vol_str = '\n'.join(vol_highlights) if vol_highlights else '（出来高急増なし）'

    if IS_MARKET_DAY:
        prompt = f"""あなたは投資チームの「銘柄選定・仮説チーム」です。本日 {TODAY} の銘柄分析を行ってください。

## 情報収集チームのレポート
{info_report[:1200]}

## スクリーニング通過銘柄（スコア6以上、RS上位20件）
{json.dumps(top20, ensure_ascii=False, indent=2)[:2500]}

## 出来高急増銘柄（vol_ratio≥1.5、本日スクリーニング通過分）
{vol_str}

## Geminiが収集した各銘柄の最新情報（出来高動向含む）
{gemini_text}

## 分析基準（ミネルヴィニStage-2）
- テクニカル: 株価>SMA50>SMA150>SMA200、SMA200上昇中、52週高値の75%以上
- RS: RS26wがプラスかつ高水準 / ファンダ: 売上・利益が前年比20%以上成長
- 出来高確認: ブレイクアウト時は平均の1.5倍以上が理想。急増出来高＝機関投資家の動き示唆

## 出力フォーマット（必ずこの形式で）
# 銘柄選定・仮説チーム レポート [{DAY_LABEL}]
日付: {TODAY}

## 市場環境評価

## 銘柄別分析

### Aランク（エントリー候補）
#### [銘柄名]（コード）
- **テクニカル判断**: （移動平均の並び・RSの状態）
- **ファンダ判断**: （売上/利益成長率・EPS傾向）
- **出来高分析**: （vol_ratio・出来高トレンド・機関動向示唆）
- **最新材料**: （Gemini情報より）
- **ランクA判定理由**: （根拠3つ以上）
- **リスク要因**: （懸念点）

### Bランク（ウォッチ継続）
#### [銘柄名]（コード）
- **ランクB判定理由**: （Aにならない理由を明記）

### Cランク（様子見）
（銘柄名・コードと一言理由のみ）

## 出来高注目銘柄（vol_ratio急増・機関動向）
（本日の出来高急増銘柄の解釈：買い集め・売り抜け・材料反応のいずれか）

## 注目パターン（VCP・カップ等）

## 総合所見
"""
    elif DAY_MODE == 'saturday':
        prev_analysis = read_report('analysis')
        prompt = f"""あなたは投資チームの「銘柄選定・仮説チーム」です。{DAY_LABEL}として今週の分析精度を振り返ってください。

## 今週の分析レポート（直近）
{prev_analysis[:2000]}

## Geminiが収集した今週の実績データ
{gemini_text}

## 出力フォーマット（必ずこの形式で）
# 銘柄選定・仮説チーム レポート [{DAY_LABEL}]
日付: {TODAY}

## 今週の分析精度振り返り
| 銘柄 | 当初ランク | 今週の実績 | 予測精度 | 改善点 |
|------|----------|-----------|---------|-------|

## 今週うまくいった分析パターン
（何が機能したか・理由）

## 今週外れた分析・改善すべき点
（何が外れたか・原因・来週への修正方針）

## 来週の注目テーマ・銘柄候補
| 銘柄 | コード | 注目理由 | 来週確認すべき点 |
|------|--------|---------|----------------|

## 分析手法改善提案
（今週の経験から導いた改善策）
"""
    else:  # sunday
        prompt = f"""あなたは投資チームの「銘柄選定・仮説チーム」です。{DAY_LABEL}として来週の銘柄を事前分析してください。

## 情報収集チームの来週準備レポート
{info_report[:1500]}

## Geminiが収集した来週の注目銘柄情報
{gemini_text}

## 出力フォーマット（必ずこの形式で）
# 銘柄選定・仮説チーム レポート [{DAY_LABEL}]
日付: {TODAY}

## 来週の事前分析（Aランク候補）
#### [銘柄名]（コード）
- **現在の状況**: （チャート形状・MA配置）
- **来週のエントリー条件**: （何が起きたらエントリーするか）
- **ファンダメンタルズ**: （成長率・業績）
- **注意すべきイベント**: （決算・材料）

## 来週の新規監視リスト候補
| 銘柄 | コード | 追加理由 |
|------|--------|---------|

## 来週の分析方針
（重点的に見るセクター・テーマ）
"""
    write_report('analysis', call_claude(prompt, max_tokens=6000))


# ─── Team 3: リスク管理 ──────────────────────────────────────────
def run_risk_management():
    portfolio = load_json('portfolio.json', {})
    info_report = read_report('info_gathering')
    analysis_report = read_report('analysis')

    pf_stocks = []
    if isinstance(portfolio, dict):
        pf_stocks = [f"{k} {v.get('name','')}" for k, v in portfolio.items() if k != '__meta__']
    elif isinstance(portfolio, list):
        pf_stocks = [f"{s.get('code','')} {s.get('name','')}" for s in portfolio]

    print(f'  [Gemini] リスク情報収集中... ({DAY_LABEL})')
    if IS_MARKET_DAY:
        if pf_stocks:
            g_prompt = f"""保有銘柄のリスク情報と市場全体のリスク要因を収集してください。

保有銘柄: {', '.join(pf_stocks[:10])}

各銘柄について:
1. 直近のネガティブニュース・下落材料
2. 決算ミス・業績下方修正の情報
3. 規制・訴訟・不祥事リスク
4. セクター全体の逆風要因
5. 地政学リスクの影響度

市場全体: VIX水準・信用スプレッド・マクロリスク（{TODAY}時点）
"""
        else:
            g_prompt = f"{TODAY} の市場全体のリスク要因を収集してください。VIX・信用スプレッド・地政学リスク・マクロリスク。"
    elif DAY_MODE == 'saturday':
        g_prompt = f"""今週の市場リスクを総括し、来週のリスクシナリオを調査してください。

1. 今週顕在化したリスク事象（実際に株価下落につながった材料）
2. 今週解消されたリスク（心配していたが影響軽微だったもの）
3. 来週に持ち越されるリスク（地政学・金融政策・決算）
4. 来週の市場の下落シナリオと確率
5. 現在のVIX水準と歴史的位置づけ
"""
    else:  # sunday
        g_prompt = f"""来週の投資リスクを事前に把握するための情報を収集してください。

1. 来週の重要イベントでの「サプライズリスク」（ネガティブ方向）
2. 週明け月曜日の市場に影響しそうな週末ニュース
3. 来週注意すべき決算（業績悪化が懸念される企業）
4. 来週の地政学リスクカレンダー
5. 現在の信用残・空売り残の水準（需給リスク）
"""
    gemini_text, sources = call_gemini(g_prompt)
    save_source_log('リスク管理チーム', sources, gemini_text)

    if IS_MARKET_DAY:
        risk_format = f"""# リスク管理チーム レポート [{DAY_LABEL}]
日付: {TODAY}

## ポートフォリオ概況
- 保有銘柄数: X / 現金比率: X%

## リスク指標
| 項目 | 現状 | 警戒水準 | 評価 |
|------|------|----------|------|
| 最大含み損率 | % | -7% | ✅/⚠️/❌ |
| ドローダウン | % | -10% | ✅/⚠️/❌ |
| セクター集中度 | % | 30% | ✅/⚠️/❌ |

## 保有銘柄リスク評価
（各銘柄の損切りラインまでの距離・最新リスク材料）

## 市場リスク（Gemini情報より）

## 損切り/縮小候補

## 推奨アクション（優先順）"""
    elif DAY_MODE == 'saturday':
        risk_format = f"""# リスク管理チーム レポート [{DAY_LABEL}]
日付: {TODAY}

## 今週のリスク総括
| リスク項目 | 今週の結果 | 来週への影響 |
|-----------|----------|------------|

## 今週の損切り実績・DD推移
（実際の損失・守れたかどうか）

## 来週のリスクシナリオ
### 警戒シナリオ（確率・トリガー・対応策）
### 基本シナリオ（最も可能性が高い展開）

## 来週のリスク管理方針
（ポジションサイズ・損切りライン・現金比率目標）"""
    else:
        risk_format = f"""# リスク管理チーム レポート [{DAY_LABEL}]
日付: {TODAY}

## 来週のリスクカレンダー
| 曜日 | リスクイベント | 影響度 | 対応方針 |
|------|-------------|-------|---------|

## 来週のポジション方針
- 最大投資比率: X%（理由）
- 1銘柄上限: X%
- 損切りルール確認

## 週明けの注意点
（月曜日に確認すべき項目）"""

    prompt = f"""あなたは投資チームの「リスク管理チーム」です。{DAY_LABEL}のリスク評価を行ってください。

## 情報収集チームのレポート
{info_report[:800]}

## 銘柄選定・仮説チームのレポート
{analysis_report[:600]}

## ポートフォリオデータ
{json.dumps(portfolio, ensure_ascii=False, indent=2)[:1500]}

## Geminiが収集したリスク情報
{gemini_text}

## 評価基準
- 損切りライン: -7〜8% / 最大DD: -10% / セクター集中上限: 30%

## 出力フォーマット
{risk_format}
"""
    write_report('risk', call_claude(prompt))


# ─── Team 4: 投資戦略 ────────────────────────────────────────────
def run_strategy():
    info_report = read_report('info_gathering')
    analysis_report = read_report('analysis')
    risk_report = read_report('risk')

    # ルールベースのフェーズ事前判定（AIへの参考情報として渡す）
    screen = load_json('screen_full_results.json', [])
    auto_phase = detect_phase(screen if isinstance(screen, list) else [])
    auto_phase_str = (
        f"ルールベース判定: {auto_phase['phase']} (スコア: {auto_phase['score']})\n"
        + '\n'.join(f"  - {r}" for r in auto_phase['reasons'])
    )

    print(f'  [Gemini] 戦略情報収集中... ({DAY_LABEL})')
    if IS_MARKET_DAY:
        g_prompt = f"""{TODAY} の投資タイミングを判断するための情報を収集してください。

1. 機関投資家・ヘッジファンドの最新ポジション動向
2. 日本株市場の需給動向（外国人・個人・信託の売買動向）
3. 信用買い残・信用売り残の水準
4. Put/Call比率・VIX・Fear&Greedインデックス
5. 機関投資家の注目テーマ・セクターローテーション動向
6. 今週のIPO・大型PO予定（需給への影響）
7. 米国市場のマネーフロー
8. 重要サポート・レジスタンス水準（日経平均・S&P500）
"""
    elif DAY_MODE == 'saturday':
        g_prompt = f"""今週の投資戦略を振り返るための情報を収集してください。

1. 今週のAttack/Steady/Defend判定の正確性（実際の市場動向と比較）
2. 今週エントリー推奨した銘柄のパフォーマンス
3. 今週の市場センチメント変化の主要因
4. 来週の市場フェーズ予測（強気・弱気の根拠）
5. 今週の機関投資家の主な売買動向
"""
    else:  # sunday
        g_prompt = f"""来週の投資戦略を立案するための情報を収集してください。

1. 現在の市場フェーズ（Attack/Steady/Defend）の判定根拠
2. 来週のエントリー好機になりそうな銘柄・セクター
3. 来週の機関投資家の動向予測
4. 来週の重要テクニカルレベル（日経・S&P500のサポート・レジスタンス）
5. 現在の信用残・Need&Greedインデックス水準
"""
    gemini_text, sources = call_gemini(g_prompt)
    save_source_log('投資戦略チーム', sources, gemini_text)

    if IS_MARKET_DAY:
        strategy_format = f"""# 投資戦略チーム レポート [{DAY_LABEL}]
日付: {TODAY}

## 市場環境判定: [Attack/Steady/Defend]
**判定理由**:
- 根拠1: ...  - 根拠2: ...  - 根拠3: ...

## 需給・センチメント評価

## 新規エントリー候補
| 銘柄 | コード | エントリー価格 | 損切り | 目標 | RR比 | 推奨サイズ | 根拠 |
|------|--------|--------------|--------|------|------|-----------|------|

## エントリー見送り理由

## 既存ポジション管理

## 本日のアクションプラン（優先順）
1. ...

## 来週以降の注目点"""
    elif DAY_MODE == 'saturday':
        strategy_format = f"""# 投資戦略チーム レポート [{DAY_LABEL}]
日付: {TODAY}

## 今週の戦略振り返り
| 判定 | 予測 | 実際 | 精度 | 学び |
|------|------|------|------|------|
| フェーズ | Attack/Steady/Defend | （実際） | ✅/❌ | |

## 今週のエントリー推奨銘柄の実績
| 銘柄 | 推奨価格 | 今週終値 | 騰落率 | 評価 |
|------|---------|---------|-------|------|

## 来週のフェーズ予測
**予測**: [Attack/Steady/Defend]
**根拠**: ...

## 来週の戦略方針
（何を重視し、どう行動するか）

## 今週の学び・戦略改善点"""
    else:  # sunday
        strategy_format = f"""# 投資戦略チーム レポート [{DAY_LABEL}]
日付: {TODAY}

## 来週の市場フェーズ判定
**判定**: [Attack/Steady/Defend]
**根拠**: 3点以上

## 来週のエントリー計画
| 銘柄 | コード | エントリー条件 | 損切り | 目標① | RR比 | 優先度 |
|------|--------|-------------|--------|-------|------|-------|

## 来週のアクションカレンダー
| 曜日 | 確認事項 | アクション |
|------|---------|----------|

## 来週の戦略上の注意点
（避けるべき行動・待つべきシグナル）"""

    prompt = f"""あなたは投資チームの「投資戦略チーム」です。{DAY_LABEL}の戦略レポートを作成してください。

## 情報収集チーム レポート
{info_report[:1000]}

## 銘柄選定・仮説チーム レポート
{analysis_report[:1500]}

## リスク管理チーム レポート
{risk_report[:800]}

## Geminiが収集した情報
{gemini_text}

## ルールベース自動判定（参考）
{auto_phase_str}
※ AIは上記を参考にしつつ、Gemini情報・各チームレポートを総合して最終判定すること

## 判定基準
- Attack: 市場トレンド上向き、RS上位銘柄が続々ブレイク、VIX低位安定
- Steady: トレンド中立、選別的エントリー可能
- Defend: 市場下落トレンド、現金保有が最優先

## 出力フォーマット
{strategy_format}
"""
    write_report('strategy', call_claude(prompt, max_tokens=5000))


# ─── Team 5: レポート統括 ─────────────────────────────────────────
def run_daily_report():
    info = read_report('info_gathering')
    analysis = read_report('analysis')
    risk = read_report('risk')
    strategy = read_report('strategy')

    print(f'  [Gemini] 追加情報収集中... ({DAY_LABEL})')
    if IS_MARKET_DAY:
        g_prompt = f"""{TODAY} 以降の投資家が注目すべき情報を収集してください。

1. 明日・今週中に予定されている主要決算発表（日米）
2. 明日以降の経済指標発表スケジュールと市場予想
3. 本日の市場引け後に発表されたニュース・決算速報
4. 明日の日本市場の注目点（先物・ADR動向）
5. 今週の重要なFRB高官発言予定
"""
    elif DAY_MODE == 'saturday':
        g_prompt = f"""今週の総括と来週の見通しをまとめるための情報を収集してください。

1. 今週の市場の総括（何が起き、何が重要だったか）
2. 今週の投資家の注目テーマ（SNS・メディアのトレンド）
3. 来週の市場を動かしそうな最重要イベント（上位3件）
4. 今週の機関投資家レポート・アナリスト見解のまとめ
5. 週末の海外市場動向（米・欧）
"""
    else:  # sunday
        g_prompt = f"""週明けの投資準備に必要な情報を収集してください。

1. 月曜日の日本株に影響する週末の米国・欧州ニュース
2. 来週の市場カレンダー（最重要イベント上位5件）
3. 週末の先物・ADR動向
4. 来週の投資テーマ・注目セクターの予測
5. 来週の投資家心理（Fear&Greed・プット/コール比率）
"""
    gemini_text, sources = call_gemini(g_prompt)
    save_source_log('レポート統括', sources, gemini_text)

    if IS_MARKET_DAY:
        report_title = f'# 📊 デイリー投資レポート {TODAY}'
        report_structure = f"""## エグゼクティブサマリー
（本日の要点を3〜5行で。市場環境判定と最重要アクションを必ず含める）

## 市場環境: [Attack/Steady/Defend]
（指数動向・センチメント・判定理由）

## 本日のアクションプラン
1. **[最優先]** ...（理由: ...）
2. ...

## 注目銘柄サマリー
| ランク | 銘柄 | コード | ポイント |
|--------|------|--------|---------|

## リスク警戒事項

## 明日以降の注目スケジュール
（Gemini情報より）

## 各チーム詳細"""
    elif DAY_MODE == 'saturday':
        report_title = f'# 📊 週次振り返りレポート {TODAY}'
        report_structure = f"""## 今週のエグゼクティブサマリー
（今週の市場・戦略・成果を5行以内で総括）

## 今週の市場環境推移
（Attack/Steady/Defendの変遷と正確性）

## 今週の成果・振り返り
| 項目 | 予測 | 実際 | 達成度 |
|------|------|------|-------|
| フェーズ判定 | | | |
| Aランク銘柄精度 | | | |
| リスク管理 | | | |

## 今週の学び（改善すべきこと3点）
1. ...

## 来週の戦略方針

## 各チームの今週の総評"""
    else:  # sunday
        report_title = f'# 📊 翌週準備レポート {TODAY}'
        report_structure = f"""## 来週のエグゼクティブサマリー
（来週の市場環境予測と戦略方針を5行以内で）

## 来週の市場フェーズ予測: [Attack/Steady/Defend]
（根拠3点以上）

## 来週のアクションカレンダー
| 曜日 | 重要イベント | 対応方針 |
|------|------------|---------|

## 来週のエントリー計画（優先順）
（Aランク候補と条件）

## 週明け月曜日のチェックリスト
（市場開始前に確認すること）

## 各チームの来週方針"""

    # ── Step2: Claude で統合レポート作成 ──
    prompt = f"""あなたは「レポート統括」です。{DAY_LABEL}の統合レポートを作成してください。

## 情報収集チーム
{info[:1500]}

## 銘柄選定・仮説チーム
{analysis[:2000]}

## リスク管理チーム
{risk[:1200]}

## 投資戦略チーム
{strategy[:1500]}

## Geminiが収集した追加情報
{gemini_text}

## 出力フォーマット（必ずこの形式で）
{report_title}

{report_structure}

## 各チーム詳細
### 情報収集チーム
（要約200字以内）
### 銘柄選定・仮説チーム
（要約200字以内）
### リスク管理チーム
（要約200字以内）
### 投資戦略チーム
（要約200字以内）

---
Generated by Investment Team System (Claude + Gemini)
"""
    result = call_claude(prompt, max_tokens=5000)
    write_report(f'{TODAY}_daily_report', result)
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
    high_rs = [s for s in screen_data if isinstance(s, dict) and s.get('rs_26w', 0) > 1.5]
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
    top_stocks = [s for s in screen_data if isinstance(s, dict) and s.get('score', 0) >= 7]
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
    rs_values = [s.get('rs_26w', 0) for s in screen_data if isinstance(s, dict) and s.get('rs_26w')]
    avg_rs = sum(rs_values) / len(rs_values) if rs_values else 0
    if avg_rs > 1.2:
        score += 1
        reasons.append(f'[事実] 全銘柄平均RS26w={avg_rs:.2f} → 市場全体が強い')
    elif avg_rs > 0.8:
        reasons.append(f'[事実] 全銘柄平均RS26w={avg_rs:.2f} → 中立水準')
    else:
        score -= 1
        reasons.append(f'[事実] 全銘柄平均RS26w={avg_rs:.2f} → 市場全体が弱い')

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
    ep = best.get('price', 0)
    stop_pct = 0.08
    target_pct = 0.25
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
        'rs_26w': best.get('rs_26w', 0),
        'score': best.get('score', 0),
        'result': None,
        'result_pct': None,
        'direction_match': None,
        'reason': f"RS26w={best.get('rs_26w',0):.2f}, score={best.get('score',0)}/7, 上位候補"
    }


def run_verification():
    """
    シミュレーション追跡 + 予測精度検証 + 他チームへのフィードバック
    - simulation_log.jsonを更新（最大3銘柄同時追跡）
    - verification.mdを生成
    """
    sim_log_path = REPORT_DIR / 'simulation_log.json'
    log = {'tracking_rule': '2週間(10営業日)追跡・最大3銘柄同時', 'actives': [], 'history': []}
    if sim_log_path.exists():
        try:
            raw = json.loads(sim_log_path.read_text(encoding='utf-8'))
            # 旧フォーマット（active単体）からの移行
            if 'active' in raw and 'actives' not in raw:
                old = raw.pop('active')
                raw['actives'] = [old] if old else []
            log = raw
        except Exception:
            pass

    screen = load_json('screen_full_results.json', [])
    stocks = screen if isinstance(screen, list) else []
    stocks_by_code = {str(s.get('code', '')): s for s in stocks if isinstance(s, dict)}

    analysis_report = read_report('analysis')
    strategy_report = read_report('strategy')
    history = log.get('history', [])
    actives = log.get('actives', [])

    # ── 各アクティブシミュレーションの更新 ──
    completion_notes = []
    remaining = []
    hypothesis_checks = []  # 仮説検証結果ログ
    for sim in actives:
        code = str(sim.get('code', ''))
        current_stock = stocks_by_code.get(code)
        prev_price = sim.get('current_price', sim.get('entry_price'))
        current_price = current_stock.get('price', prev_price) if current_stock else prev_price
        entry = sim['entry_price']
        stop = sim['stop_loss']
        target1 = sim['target1']

        days_elapsed = sim.get('days_elapsed', 0) + (1 if IS_MARKET_DAY else 0)
        sim['days_elapsed'] = days_elapsed
        sim['current_price'] = current_price
        pct = (current_price - entry) / entry * 100 if entry else 0
        sim['current_pct'] = round(pct, 2)

        # ── 前日仮説の検証（平日のみ） ──
        if IS_MARKET_DAY and sim.get('next_hypothesis') and prev_price:
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
            # 検証済み仮説はクリア（新しいものを後で生成）
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
        elif days_elapsed >= 10:
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

    # ── 空きスロットを埋める（平日のみ） ──
    new_sim_notes = []
    if IS_MARKET_DAY and len(actives) < MAX_SIM_SLOTS:
        a_rank_stocks = sorted(
            [s for s in stocks if isinstance(s, dict) and s.get('score', 0) >= 7],
            key=lambda x: x.get('rs_26w', 0), reverse=True
        )
        # 直近30日のhistory + 現在actives で使用済みコードを除外
        used_codes = {str(h.get('code', '')) for h in history if h.get('start_date', '') >= (
            __import__('datetime').date.today() - __import__('datetime').timedelta(days=30)
        ).isoformat()}
        used_codes |= {str(a.get('code', '')) for a in actives}
        candidates = [s for s in a_rank_stocks if str(s.get('code', '')) not in used_codes]

        slots_to_fill = MAX_SIM_SLOTS - len(actives)
        for best in candidates[:slots_to_fill]:
            new_sim = _make_new_sim(best)
            actives.append(new_sim)
            new_sim_notes.append(f"新規: {best.get('name','')}({best.get('code','')}) EP={best.get('price',0):.0f}円")

    # ── 翌日仮説の生成（平日のみ・仮説がないアクティブ対象） ──
    sims_needing_hypothesis = [s for s in actives if IS_MARKET_DAY and not s.get('next_hypothesis')]
    if sims_needing_hypothesis:
        print(f'  [Claude] 翌日仮説生成中... ({len(sims_needing_hypothesis)}銘柄)')
        sims_str = json.dumps([{
            'code': s['code'], 'name': s['name'],
            'entry_price': s['entry_price'], 'current_price': s['current_price'],
            'current_pct': s['current_pct'], 'days_elapsed': s['days_elapsed'],
            'stop_loss': s['stop_loss'], 'target1': s['target1'],
            'rs_26w': s.get('rs_26w', 0),
            'hypothesis_history': s.get('hypothesis_history', [])[-3:]
        } for s in sims_needing_hypothesis], ensure_ascii=False, indent=2)

        hyp_prompt = f"""あなたは投資チームの「銘柄選定・仮説チーム（テクニカル担当）」です。
以下の追跡中銘柄について、翌営業日（{TODAY}の翌日）の株価方向仮説を立ててください。

## 追跡銘柄
{sims_str}

## 要求
各銘柄について以下をJSON配列で返してください（必ずJSONのみ、説明文不要）:
[
  {{
    "code": "銘柄コード",
    "direction": "上昇" or "下落" or "横ばい",
    "reason": "根拠（テクニカル・モメンタム・市場環境から50文字以内）",
    "confidence": "高" or "中" or "低",
    "key_level": "注目価格水準（例: 1050円の抵抗帯）"
  }}
]"""
        hyp_response = call_claude(hyp_prompt, max_tokens=1000)
        try:
            import re as _re
            json_match = _re.search(r'\[[\s\S]*\]', hyp_response)
            if json_match:
                hypotheses = json.loads(json_match.group())
                hyp_by_code = {h['code']: h for h in hypotheses if isinstance(h, dict)}
                for sim in sims_needing_hypothesis:
                    hyp = hyp_by_code.get(sim['code'])
                    if hyp:
                        sim['next_hypothesis'] = {
                            'date': TODAY,
                            'direction': hyp.get('direction', ''),
                            'reason': hyp.get('reason', ''),
                            'confidence': hyp.get('confidence', ''),
                            'key_level': hyp.get('key_level', '')
                        }
        except Exception as e:
            print(f'  [警告] 仮説JSON解析失敗: {e}')

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

    # ── Gemini: 精度向上のための情報収集 ──
    print(f'  [Gemini] 検証情報収集中... ({DAY_LABEL})')
    active_names = ', '.join(a['name'] for a in actives) if actives else 'なし'
    hyp_check_str = '\n'.join(hypothesis_checks) if hypothesis_checks else 'なし（週末または仮説未設定）'
    # 仮説精度計算
    all_hyp = [h for a in (actives + history) for h in a.get('hypothesis_history', [])]
    hyp_total = len(all_hyp)
    hyp_hits = sum(1 for h in all_hyp if h.get('match'))
    hyp_accuracy = hyp_hits / hyp_total * 100 if hyp_total else 0
    sim_summary = f"追跡中({len(actives)}件): {active_names} / 累計{len(completed)}件完了 / 勝率{win_rate:.0f}% / 仮説的中率{hyp_accuracy:.0f}%"
    g_prompt = f"""投資シミュレーションの精度向上に役立つ情報を収集してください。

現在の状況: {sim_summary}

1. ミネルヴィニ戦略における損切り-8%・目標+25%・2週間追跡の有効性に関する研究・事例
2. 日本株でのモメンタム投資の勝率・期待値に関する統計データ
3. RS（相対強度）指標の精度を高めるための改善手法
4. 個人投資家がシミュレーションから学ぶための効果的な分析手法
5. 機械学習・AIを使った株価予測精度の現状（参考として）
"""
    gemini_text, sources = call_gemini(g_prompt)
    save_source_log('シミュレーション追跡・検証チーム', sources, gemini_text)

    # ── Claude: 検証レポート生成 ──
    history_str = json.dumps(history[-10:], ensure_ascii=False, indent=2) if history else '（履歴なし）'
    actives_str = json.dumps(actives, ensure_ascii=False, indent=2) if actives else '（なし）'

    # アクティブ追跡テーブル行生成
    active_table_rows = ''
    for a in actives:
        active_table_rows += f"| {a['name']}（{a['code']}） | {a['entry_price']}円 | {a['current_price']}円（{a['current_pct']:+.1f}%） | {a['stop_loss']}円 | {a['target1']}円 | {a['days_elapsed']}/10日 |\n"
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
| 翌日仮説的中率 | {hyp_accuracy:.1f}% | 55%以上 | {'✅' if hyp_accuracy >= 55 else '⚠️' if hyp_total else '-'} |
| 平均利益 | {avg_win:+.1f}% | +25%以上 | {'✅' if avg_win >= 25 else '⚠️' if wins else '-'} |
| 平均損失 | {avg_loss:+.1f}% | -8%以内 | {'✅' if avg_loss >= -8 else '⚠️' if losses else '-'} |

## 翌日仮説検証（本日の差異分析）
担当: **銘柄選定・仮説チーム（テクニカル担当）→ シミュレーション追跡・検証チーム**
（本日の仮説結果: {hyp_check_str}）
（外れた場合は具体的な原因を分析: 想定外の材料、サポート割れ、出来高異常等）

## 明日の仮説（銘柄選定・仮説チームが生成済み）
（simulation_log.jsonのnext_hypothesisフィールドに記録済み。各銘柄の根拠を補足説明）

## 直近の結果振り返り
担当: **シミュレーション追跡・検証チーム**
（直近3件の売買結果: 予測 vs 実際を分析し、外れた原因を明記）

## 分析精度の改善提案
### → 銘柄選定・仮説チームへ（担当: シミュレーション追跡・検証チーム →銘柄選定・仮説チーム）
（Aランク選定基準の改善点）

### → 投資戦略チームへ（担当: シミュレーション追跡・検証チーム →投資戦略チーム）
（エントリータイミング・損切り設定の改善点）

## 学習パターン
担当: **シミュレーション追跡・検証チーム**
（蓄積データから見えてきた傾向・法則）

## 参考: 精度向上のためのベストプラクティス
（Gemini情報より）
"""
    write_report('verification', call_claude(prompt, max_tokens=5000))


# ─── Team 6: セキュリティ ─────────────────────────────────────────
def run_security():
    import subprocess
    git_log = subprocess.run(
        ['git', 'log', '--oneline', '-20'],
        capture_output=True, text=True
    ).stdout

    # ── Step1: Gemini で最新のセキュリティ脅威・脆弱性情報を収集 ──
    print('  [Gemini] セキュリティ脅威情報収集中...')
    g_prompt = f"""{TODAY} の最新サイバーセキュリティ・金融システムセキュリティ情報を収集してください。

1. 金融・投資システムを狙った最新サイバー攻撃・フィッシング事例
2. Python/GitHub Actions/Vercel に関する最新脆弱性（CVE情報）
3. APIキー漏洩・クレデンシャル流出に関する最新インシデント事例
4. 個人投資家を狙った詐欺・セキュリティ被害の最新情報
5. anthropic/google AI API に関するセキュリティアドバイザリ
"""
    gemini_text, sources = call_gemini(g_prompt)
    save_source_log('セキュリティチーム', sources, gemini_text)

    # ── Step2: Claude でコード監査＋レポート作成 ──
    prompt = f"""あなたは「情報セキュリティチーム」です。本日 {TODAY} のセキュリティ監査を行ってください。

## Gitコミット履歴（直近20件）
{git_log}

## Geminiが収集した最新セキュリティ脅威情報
{gemini_text}

## 内部チェック項目
1. コミットメッセージに `key`, `secret`, `password`, `token` が含まれていないか
2. index.htmlに外部CDNスクリプトが追加されていないか（プロジェクトルールで禁止）
3. APIキーがハードコードされていないか（`sk-`, `AIza`, `Bearer`パターン）
4. Vercel serverless関数（api/claude.js, api/gemini.js）の実装に問題がないか
5. GitHub Actions workflowにシークレット漏洩リスクがないか

## 既知の安全設計（False Positive除外）
- APIキーはVercel環境変数で管理（サーバーサイド）
- Gemini APIキーはHTTPヘッダーで送らない（CORS対策）
- ANTHROPIC_API_KEY / GEMINI_API はGitHub Secrets + Vercel Env Varsで管理

## 出力フォーマット（必ずこの形式で）
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

## 外部脅威情報（Geminiより）
（本システムに関連するリスクを抽出して記載）

## 要対応事項
（なければ「なし」）

## 推奨事項
...
"""
    write_report('security', call_claude(prompt))


# ─── Team 7: 内部監査 ─────────────────────────────────────────────
def run_internal_audit():
    # 各チームのレポートを読む
    reports = {
        '情報収集': read_report('info_gathering'),
        '分析':     read_report('analysis'),
        'リスク管理': read_report('risk'),
        '投資戦略': read_report('strategy'),
        'セキュリティ': read_report('security'),
        '統括レポート': read_report(f'{TODAY}_daily_report'),
    }

    # 過去の日次レポートを最大5件取得
    past_reports = []
    for p in sorted(REPORT_DIR.glob('*_daily_report.md'), reverse=True):
        if p.stem != f'{TODAY}_daily_report':
            past_reports.append(p.read_text(encoding='utf-8')[:500])
        if len(past_reports) >= 5:
            break
    past_str = '\n---\n'.join(past_reports) if past_reports else '（過去レポートなし）'

    # 監査ログを読む（前回の提案フォローアップ用）
    audit_log_path = Path('reports') / 'audit_log.md'
    prev_audit = audit_log_path.read_text(encoding='utf-8')[-2000:] if audit_log_path.exists() else '（初回）'

    reports_str = '\n\n'.join(f'### {name}\n{content[:1000]}' for name, content in reports.items())

    # ── Step1: Gemini で優れた投資チーム運営のベストプラクティスを調査 ──
    print('  [Gemini] 投資チーム改善情報収集中...')
    g_prompt = f"""プロの投資チーム（ヘッジファンド・資産運用会社）の運営ベストプラクティスについて調査してください。

1. 優れた株式分析レポートの構成要素・品質基準
2. ミネルヴィニ流成長株投資における最新の手法・改善点
3. AIを活用した投資分析の最新事例・ベストプラクティス
4. 個人投資家がプロに近づくための情報収集・分析手法
5. 投資チームの意思決定プロセス改善事例

本日 {TODAY} の情報を含めてください。
"""
    gemini_text, sources = call_gemini(g_prompt)
    save_source_log('内部監査チーム', sources, gemini_text)

    kpi_definitions = build_kpi_check_prompt()

    prompt = f"""あなたは投資チームの「内部監査チーム」です。本日 {TODAY} の全チームを監査し、KPI達成状況を評価して改善提案を行ってください。

## 各チームのKPI定義
{kpi_definitions}

## 本日の各チームレポート
{reports_str}

## 過去レポートのサマリー（最大5件）
{past_str}

## 前回の監査ログ（フォローアップ用）
{prev_audit}

## Geminiが収集した投資チームのベストプラクティス
{gemini_text}

## 評価観点（各5段階）
- 網羅性: KPI定義の全項目をカバーしているか
- 具体性: 数値・銘柄コード・根拠が明記されているか
- 有用性: 投資判断に実際に役立つ内容か
- 一貫性: 過去レポートと矛盾がないか
- 連携性: 前チームの情報を適切に引き継いでいるか
- AI活用度: Gemini+Claudeの二重確認が有効に機能しているか

## 出力フォーマット（必ずこの形式で）
# 内部監査チーム レポート
日付: {TODAY}

## エグゼクティブサマリー
（最重要発見を3点以内で）

## KPI達成状況
| チーム | KPI項目 | 目標 | 達成状況 | 評価 |
|--------|---------|------|---------|------|
| 情報収集 | 必須8項目網羅率 | 100% | XX% | ✅/⚠️/❌ |
| 情報収集 | データ誤り件数 | 0件 | X件 | ✅/⚠️/❌ |
| 分析 | 評価銘柄数 | 5銘柄以上 | X銘柄 | ✅/⚠️/❌ |
| 分析 | 判断理由の具体性 | 根拠3つ以上 | X個 | ✅/⚠️/❌ |
| リスク管理 | DD許容上限遵守 | -10%以内 | XX% | ✅/⚠️/❌ |
| リスク管理 | 損切りライン設定率 | 100% | XX% | ✅/⚠️/❌ |
| 投資戦略 | 平均RR比 | 3.0以上 | X.X | ✅/⚠️/❌ |
| 投資戦略 | アクションプランの具体性 | 全項目明記 | ✅/❌ | ✅/⚠️/❌ |
| レポート統括 | 全チーム統合率 | 100% | XX% | ✅/⚠️/❌ |
| レポート統括 | [事実]/[AI分析]ラベル | 100% | XX% | ✅/⚠️/❌ |
| セキュリティ | 重大脆弱性未報告 | 0件 | X件 | ✅/⚠️/❌ |
| 内部監査 | 前回提案フォローアップ | 100% | XX% | ✅/⚠️/❌ |
（本日評価できないKPIは「-」と記載）

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
（繰り返し未達成のKPI・改善傾向）

## 改善提案
### 優先度: 高（KPI未達成に直結）
...
### 優先度: 中（品質向上）
...

## 新チーム・新KPI提案
（不足機能や追加すべきKPIがあれば）

## 前回提案のフォローアップ
...
"""
    result = call_claude(prompt, max_tokens=6000)
    write_report('internal_audit', result)

    # KPIログ: チーム別スコアをJSONで保存（トレンド分析用）
    kpi_scores = {}
    for line in result.split('\n'):
        # "| チーム名 | X | X | X | X | X | X | X |" の行をパース
        parts = [p.strip() for p in line.split('|') if p.strip()]
        if len(parts) >= 8 and parts[0] in ['情報収集', '分析', 'リスク管理', '投資戦略', '統括', 'セキュリティ']:
            try:
                kpi_scores[parts[0]] = {
                    'coverage': parts[1], 'specificity': parts[2],
                    'usefulness': parts[3], 'consistency': parts[4],
                    'linkage': parts[5], 'ai_usage': parts[6], 'total': parts[7]
                }
            except IndexError:
                pass
    save_kpi_log(kpi_scores)

    # 監査ログに追記
    audit_log_path = Path('reports') / 'audit_log.md'
    summary_lines = [l for l in result.split('\n') if l.startswith('- ') or l.startswith('### 優先度')][:10]
    log_entry = f'\n## {TODAY}\n' + '\n'.join(summary_lines) + '\n'
    existing = audit_log_path.read_text(encoding='utf-8') if audit_log_path.exists() else '# 内部監査ログ\n'
    audit_log_path.write_text(existing + log_entry, encoding='utf-8')
    print(f'  -> audit_log.md 更新')


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
}

if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else 'all'

    if target == 'all':
        for key, (name, fn) in TEAMS.items():
            print(f'\n[{name}] 開始...')
            try:
                fn()
                print(f'[{name}] 完了')
            except Exception as e:
                print(f'[{name}] エラー: {e}', file=sys.stderr)
    elif target in TEAMS:
        name, fn = TEAMS[target]
        print(f'[{name}] 開始...')
        fn()
        print(f'[{name}] 完了')
    else:
        print(f'不明なチーム: {target}')
        print(f'使用可能: {list(TEAMS.keys())} または all')
        sys.exit(1)

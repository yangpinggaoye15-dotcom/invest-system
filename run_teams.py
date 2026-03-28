#!/usr/bin/env python3
"""
Investment Team System - GitHub Actions runner
各チームがClaude APIを呼び出してレポートを生成する
"""
import anthropic
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST).strftime('%Y-%m-%d')
DATA_DIR = Path(os.environ.get('INVEST_DATA_DIR', 'invest-data'))
REPORT_DIR = Path('reports') / 'daily'
REPORT_DIR.mkdir(parents=True, exist_ok=True)

client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
MODEL = 'claude-sonnet-4-6'


def call_claude(prompt: str, max_tokens: int = 4096) -> str:
    msg = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}]
    )
    return msg.content[0].text


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

    prompt = f"""あなたは投資チームの「情報収集チーム」です。本日 {TODAY} の市場情報を収集してレポートを作成してください。

## 作業内容
WebSearchで以下を調べてください:
1. 本日/前日の日経平均・S&P500・ダウ・NASDAQの終値と前日比
2. 本日〜今週の注目経済イベント（決算・経済指標・中央銀行）
3. 前日に特に動いたセクター（上昇・下落）
4. ドル円・米10年債利回りの動向

## スクリーニングデータ（自動取得済み）
スキャン銘柄数: {total}
RS26w上位10銘柄:
{top_str}

## 出力フォーマット（必ずこの形式で）
# 情報収集チーム レポート
日付: {TODAY}

## 市場概況
（表形式: 指数・終値・前日比）

## 本日の注目イベント
...

## セクター動向
...

## 為替・金利
...

## スクリーニング状況
スキャン: {total}銘柄 / RS上位10銘柄（上記データを整理して記載）
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

    prompt = f"""あなたは投資チームの「分析チーム」です。本日 {TODAY} の銘柄分析を行ってください。

## 情報収集チームのレポート（参考）
{info_report[:1500]}

## スクリーニング通過銘柄（スコア6以上、RS上位20件）
{json.dumps(top20, ensure_ascii=False, indent=2)[:3000]}

## 作業内容
1. 上記銘柄をミネルヴィニのStage-2基準で評価（移動平均の並び・RS・出来高）
2. 各銘柄をA/B/Cでランク付け
   - A: エントリー候補（今すぐ注目）
   - B: ウォッチリスト継続
   - C: 様子見
3. VCP・カップウィズハンドル・フラットベースなどのパターン候補を特定

## 出力フォーマット（必ずこの形式で）
# 分析チーム レポート
日付: {TODAY}

## テクニカル分析サマリー
...

## 銘柄ランキング
| 銘柄 | コード | ランク | RS26w | 根拠 |
|------|--------|--------|-------|------|
...

## 注目パターン
...

## ファンダメンタルハイライト
...
"""
    write_report('analysis', call_claude(prompt))


# ─── Team 3: リスク管理 ──────────────────────────────────────────
def run_risk_management():
    portfolio = load_json('portfolio.json', {})
    info_report = read_report('info_gathering')
    analysis_report = read_report('analysis')

    prompt = f"""あなたは投資チームの「リスク管理チーム」です。本日 {TODAY} のリスク評価を行ってください。

## 情報収集チームのレポート（要約）
{info_report[:1000]}

## 分析チームのレポート（要約）
{analysis_report[:1000]}

## 現在のポートフォリオデータ
{json.dumps(portfolio, ensure_ascii=False, indent=2)[:2000]}

## 作業内容
1. ポートフォリオリスク評価（損切りラインまでの距離、セクター集中度、現金比率）
2. 市場リスク評価（指数のトレンド健全性、地政学リスク）
3. ドローダウン管理（含み損益、最大許容ドローダウン-10%への余裕）
4. 損切り・縮小候補の提示

## 出力フォーマット（必ずこの形式で）
# リスク管理チーム レポート
日付: {TODAY}

## ポートフォリオ概況
- 保有銘柄数: X / 現金比率: X%

## リスク指標
...

## セクター集中度
...

## 損切り/縮小候補
...

## 推奨アクション
...
"""
    write_report('risk', call_claude(prompt))


# ─── Team 4: 投資戦略 ────────────────────────────────────────────
def run_strategy():
    info_report = read_report('info_gathering')
    analysis_report = read_report('analysis')
    risk_report = read_report('risk')

    prompt = f"""あなたは投資チームの「投資戦略チーム」です。本日 {TODAY} の投資戦略を策定してください。

## 情報収集チーム レポート
{info_report[:1200]}

## 分析チーム レポート
{analysis_report[:1200]}

## リスク管理チーム レポート
{risk_report[:1200]}

## 作業内容
1. 市場環境判定: Attack（積極）/ Steady（通常）/ Defend（守り）
2. 新規エントリー候補（Aランク銘柄から、RR比3:1以上のもの）
   - エントリーポイント・損切りライン・目標価格・ポジションサイズ
3. 既存ポジション管理（利確・損切り・トレーリングストップ更新）
4. 本日の具体的アクションプラン

## 出力フォーマット（必ずこの形式で）
# 投資戦略チーム レポート
日付: {TODAY}

## 市場環境判定: [Attack/Steady/Defend]
（判定理由）

## 新規エントリー候補
| 銘柄 | コード | エントリー | 損切り | 目標 | RR比 | サイズ |
|------|--------|-----------|--------|------|------|--------|
...

## 既存ポジション管理
...

## 本日のアクションプラン
1. ...
2. ...
"""
    write_report('strategy', call_claude(prompt))


# ─── Team 5: レポート統括 ─────────────────────────────────────────
def run_daily_report():
    info = read_report('info_gathering')
    analysis = read_report('analysis')
    risk = read_report('risk')
    strategy = read_report('strategy')

    prompt = f"""あなたは「レポート統括」です。4チームのレポートを統合した日次レポートを作成してください。

## 情報収集チーム
{info[:1800]}

## 分析チーム
{analysis[:1800]}

## リスク管理チーム
{risk[:1200]}

## 投資戦略チーム
{strategy[:1800]}

## 出力フォーマット（必ずこの形式で）
# 📊 デイリー投資レポート {TODAY}

## エグゼクティブサマリー
（3行以内で本日の要点）

## 市場環境
...

## 分析ハイライト
...

## リスク状況
...

## 本日のアクションプラン
1. ...
2. ...

## 各チーム詳細
### 情報収集チーム
...
### 分析チーム
...
### リスク管理チーム
...
### 投資戦略チーム
...

---
Generated by Investment Team System
"""
    result = call_claude(prompt)
    write_report(f'{TODAY}_daily_report', result)
    # latest_report.md は常に上書き（スマホから簡単に取得できるように）
    write_report('latest_report', result)


# ─── Team 6: セキュリティ ─────────────────────────────────────────
def run_security():
    import subprocess
    git_log = subprocess.run(
        ['git', 'log', '--oneline', '-20'],
        capture_output=True, text=True
    ).stdout

    prompt = f"""あなたは「情報セキュリティチーム」です。本日 {TODAY} のセキュリティ監査を行ってください。

## Gitコミット履歴（直近20件）
{git_log}

## チェック項目
1. コミットメッセージに `key`, `secret`, `password`, `token` が含まれていないか
2. index.htmlに外部CDNスクリプトが追加されていないか（プロジェクトルールで禁止）
3. APIキーがハードコードされていないか（`sk-`, `AIza`, `Bearer `パターン）
4. .gitignoreに `.env`, `*.key` が含まれているか

## 既知の安全事項（False Positive除外）
- APIキーはブラウザlocalStorage（`gk`, `ck`キー）で管理（意図的）
- `sessionStorage`は使用禁止（CLAUDE.mdルール）
- Gemini APIキーはHTTPヘッダーで送らない（CORS対策）

## 出力フォーマット（必ずこの形式で）
# 情報セキュリティチーム レポート
日付: {TODAY}

## 総合評価: [GREEN / YELLOW / RED]

## チェック結果
| 項目 | 状態 | 詳細 |
|------|------|------|
| コミット履歴 | ✅/⚠️/❌ | ... |
| CDNスクリプト | ✅/⚠️/❌ | ... |
| APIキー露出 | ✅/⚠️/❌ | ... |
| .gitignore設定 | ✅/⚠️/❌ | ... |

## 要対応事項
（なければ「なし」）

## 推奨事項
...
"""
    write_report('security', call_claude(prompt))


# ─── メイン ──────────────────────────────────────────────────────
TEAMS = {
    'info':     ('情報収集チーム',   run_info_gathering),
    'analysis': ('分析チーム',       run_analysis),
    'risk':     ('リスク管理チーム', run_risk_management),
    'strategy': ('投資戦略チーム',   run_strategy),
    'report':   ('レポート統括',     run_daily_report),
    'security': ('セキュリティチーム', run_security),
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

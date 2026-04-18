"""チーム共通の基礎ヘルパー: API 呼び出し・ファイル I/O・知識管理。

run_teams.py から抽出した純粋な補助関数群。
teams/_context と teams/_config のみに依存する。
"""
from __future__ import annotations

import json
import re as _re
from pathlib import Path

import requests

from teams._config import TEAM_KPIS, SOURCE_RELIABILITY
from teams._context import (
    TODAY, WEEKDAY,
    DATA_DIR, REPORT_DIR,
    client, MODEL, GEMINI_KEY, GEMINI_URL,
)


def call_claude(prompt: str, max_tokens: int = 4096, inject_labels: bool = True) -> str:
    """Claude API呼び出し。inject_labels=True（デフォルト）でLABEL_RULEを自動付与。"""
    full_prompt = prompt + LABEL_RULE if inject_labels else prompt
    msg = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': full_prompt}]
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
    for attempt in range(3):
        try:
            resp = requests.post(f'{GEMINI_URL}?key={GEMINI_KEY}', json=payload, timeout=120)
            break
        except requests.exceptions.Timeout:
            if attempt == 2:
                return '（Gemini タイムアウト - 市場データ取得不可）', []
            import time; time.sleep(5)
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


def _fetch_fresh_price(code: str, fallback: float) -> float:
    """J-Quants V2 から最新終値を直接取得する。
    - 当日データがあればその終値を返す
    - 当日データ未更新（15:30前など）なら直近5営業日の最終バーを返す
    - 取得失敗時は fallback をそのまま返す
    """
    jq_key = os.environ.get('JQUANTS_API_KEY', '')
    if not jq_key:
        return fallback
    try:
        code5 = str(code).zfill(4) + '0'
        headers = {'x-api-key': jq_key}
        today_s = NOW_JST.strftime('%Y%m%d')
        past_s  = (NOW_JST - timedelta(days=7)).strftime('%Y%m%d')
        url = (f'https://api.jquants.com/v2/equities/bars/daily'
               f'?code={code5}&from={past_s}&to={today_s}')
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        bars = resp.json().get('data', [])
        if bars:
            last = bars[-1]
            price = last.get('AdjClose') or last.get('Close') or fallback
            return float(price)
    except Exception as e:
        print(f'  [警告] J-Quants価格取得失敗 ({code}): {e}')
    return fallback


# ─── ラベルルール（全チーム共通・全プロンプトに必ず含める） ─────────
LABEL_RULE = """
---
**【必須ルール: ラベル付け】**
レポート内の全ての情報に以下のラベルを付けること:
- `[事実]` : 市場データ・数値・ニュース等の客観的事実
- `[AI分析]` : AIの推論・判断・予測・解釈

例: `[事実] 日経平均は前日比-1.2%の38,500円で引けた。`
例: `[AI分析] 下落の主因は米国長期金利上昇による割高株の売りと推定される。`
ラベルなしの文章は禁止。全セクションに必ず付けること。
"""


def read_report(name: str) -> str:
    path = REPORT_DIR / f'{name}.md'
    return path.read_text(encoding='utf-8') if path.exists() else '（未生成）'


def is_generated(report_content: str) -> bool:
    """レポートが生成済みかどうかを返す"""
    return report_content != '（未生成）'


def screen_to_list(screen) -> list:
    """screen_full_results.json はdict形式（コードをキー）またはlist形式。
    どちらでもエラー銘柄を除いたリストに変換する。"""
    if isinstance(screen, list):
        return [s for s in screen if isinstance(s, dict) and not s.get('error')]
    elif isinstance(screen, dict):
        return [v for v in screen.values()
                if isinstance(v, dict) and 'code' in v and not v.get('error')]
    return []


def _score_num(stock: dict) -> int:
    """score フィールド（"5/7" 形式 or int or None）→ 0〜7の整数に変換。
    screen_full_results.json は "n/7" 文字列で保存される。"""
    v = stock.get('score') or 0
    if isinstance(v, str) and '/' in v:
        try:
            return int(v.split('/')[0])
        except (ValueError, IndexError):
            return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _rs26w(stock: dict) -> float:
    """RS値を float で返す（None/missing → 0.0）。
    新フィールド rs50w（週足n=50）を優先、旧フィールド rs26w/rs_26w にフォールバック。"""
    v = stock.get('rs50w') or stock.get('rs30w') or stock.get('rs26w') or stock.get('rs_26w') or 0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def write_report(name: str, content: str):
    path = REPORT_DIR / f'{name}.md'
    path.write_text(content, encoding='utf-8')
    print(f'  -> {path}')


def save_kpi_log(kpi_results: dict):
    """KPI達成状況を kpi_log.json に追記（日次トレンド分析用）"""
    log_path = REPORT_DIR / 'kpi_log.json'
    existing = []
    # ローカルになければinvest-dataから読む（GitHub Actions環境対応）
    for _candidate in [log_path, DATA_DIR / 'reports' / 'kpi_log.json']:
        if _candidate.exists():
            try:
                existing = json.loads(_candidate.read_text(encoding='utf-8'))
                break
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


# ─── 共有情報ハブ（shared_context） ──────────────────────────────
SHARED_CTX_PATH = REPORT_DIR / 'shared_context.md'

def read_shared_context() -> str:
    return SHARED_CTX_PATH.read_text(encoding='utf-8') if SHARED_CTX_PATH.exists() else '（共有情報なし）'

def update_shared_context(team_name: str, summary: str):
    """shared_context.md のチームセクションを更新する"""
    existing = SHARED_CTX_PATH.read_text(encoding='utf-8') if SHARED_CTX_PATH.exists() else f'# shared_context.md（{TODAY}更新）\n'
    import re as _re
    section = f'## {team_name}'
    new_block = f'{section}\n{summary}\n'
    if section in existing:
        existing = _re.sub(rf'{_re.escape(section)}\n.*?(?=\n##|\Z)', new_block, existing, flags=_re.DOTALL)
    else:
        existing += f'\n{new_block}'
    SHARED_CTX_PATH.write_text(existing, encoding='utf-8')

def get_feedback_prefix(team_key: str) -> str:
    """Team5の改善提案とTeam9のインセンティブをプロンプト冒頭に注入"""
    lines = []
    # Team5（内部監査）の改善提案
    audit = read_report('internal_audit')
    if audit != '（未生成）':
        # 改善提案セクションを抽出（最大200文字）
        import re as _re
        m = _re.search(r'## 改善提案.*?\n(.*?)(?=\n##|\Z)', audit, _re.DOTALL)
        if m:
            suggestion = m.group(1).strip()[:200]
            lines.append(f'【前回監査の改善提案】{suggestion}')
    # Team8（検証）の仮説的中率 → Team2のみ
    if team_key == 'analysis':
        verification = read_report('verification')
        if verification != '（未生成）':
            import re as _re
            m = _re.search(r'仮説的中率.*?(\d+\.?\d*)%', verification)
            if m:
                lines.append(f'【仮説的中率（累積）】{m.group(1)}%（目標60%）')
            # 差異分析サマリー
            m2 = _re.search(r'## (仮説検証結果|差異分析)(.*?)(?=\n##|\Z)', verification, _re.DOTALL)
            if m2:
                lines.append(f'【前日差異分析】{m2.group(2).strip()[:300]}')
    return '\n'.join(lines) + '\n\n' if lines else ''


# ─── 知識管理システム（自律学習のための永続化） ─────────────────────────────
KNOWLEDGE_DIR = Path('knowledge')
KNOWLEDGE_DIR.mkdir(exist_ok=True)

def read_knowledge(key: str, max_chars: int = 3000) -> str:
    """過去に蓄積した知識・パターン・洞察を読む"""
    path = KNOWLEDGE_DIR / f'{key}.md'
    if path.exists():
        content = path.read_text(encoding='utf-8')
        return content[-max_chars:] if len(content) > max_chars else content
    return '（知識なし: 初回実行）'

def write_knowledge(key: str, content: str):
    """今日の洞察・学びを将来の参考のために保存する（直近30エントリ保持）"""
    path = KNOWLEDGE_DIR / f'{key}.md'
    header = f'# {key} Knowledge Base\n'
    existing = path.read_text(encoding='utf-8') if path.exists() else header
    entry = f'\n## {TODAY}\n{content}\n'
    # 「## YYYY-MM-DD」区切りで直近30エントリを保持
    sections = existing.split('\n## 20')
    if len(sections) > 31:
        sections = sections[:1] + sections[-30:]
    new_content = '\n## 20'.join(sections) + entry
    path.write_text(new_content, encoding='utf-8')
    print(f'    [知識保存] knowledge/{key}.md 更新')



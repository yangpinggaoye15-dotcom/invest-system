#!/usr/bin/env python3
"""
daily_data_prep.py  –  Scheduled Tasks 用データ準備スクリプト
Claude API を一切使わず、全チームに必要なデータを収集・整形して
reports/daily/daily_context.json に出力する。

実行: python scripts/daily_data_prep.py
"""
import json, os, subprocess, sys, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── .env 読み込み ──────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent

def _load_env():
    env_file = BASE_DIR / '.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env()

JST          = timezone(timedelta(hours=9))
NOW_JST      = datetime.now(JST)
TODAY        = NOW_JST.strftime('%Y-%m-%d')
WEEKDAY      = NOW_JST.weekday()          # 0=月 … 4=金, 5=土, 6=日
IS_MARKET_DAY = WEEKDAY < 5

DATA_DIR     = Path(os.environ.get('INVEST_DATA_DIR', str(BASE_DIR / 'invest-data')))
REPORT_DIR   = BASE_DIR / 'reports' / 'daily'
KNOWLEDGE_DIR = BASE_DIR / 'knowledge'
PYTHON       = sys.executable

GEMINI_KEY  = os.environ.get('GEMINI_API', '')
GEMINI_URL  = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'
JQUANTS_KEY = os.environ.get('JQUANTS_API_KEY', '')

KNOWLEDGE_KEYS = [
    'info_patterns', 'analysis_patterns', 'risk_patterns', 'strategy_patterns',
    'report_patterns', 'security_patterns', 'audit_patterns', 'verification_patterns',
    'hr_patterns', 'fix_patterns',
]


# ── API ヘルパー ───────────────────────────────────────────────────
def call_gemini(query: str) -> str:
    if not GEMINI_KEY:
        return '（Gemini APIキー未設定）'
    payload = {
        'contents': [{'parts': [{'text': query}]}],
        'tools': [{'google_search': {}}],
    }
    for attempt in range(3):
        try:
            resp = requests.post(f'{GEMINI_URL}?key={GEMINI_KEY}', json=payload, timeout=120)
            data = resp.json()
            cand = (data.get('candidates') or [{}])[0]
            text = (cand.get('content', {}).get('parts') or [{}])[0].get('text', '')
            return text[:4000]
        except requests.exceptions.Timeout:
            if attempt == 2:
                return '（Gemini タイムアウト）'
            import time; time.sleep(5)
        except Exception as e:
            return f'（Gemini エラー: {e}）'
    return '（Gemini 失敗）'


def fetch_fresh_price(code: str, fallback: float = 0.0) -> float:
    if not JQUANTS_KEY:
        return fallback
    try:
        code5 = str(code).zfill(4) + '0'
        headers = {'x-api-key': JQUANTS_KEY}
        today_s = NOW_JST.strftime('%Y%m%d')
        past_s  = (NOW_JST - timedelta(days=7)).strftime('%Y%m%d')
        url = (f'https://api.jquants.com/v2/equities/bars/daily'
               f'?code={code5}&from={past_s}&to={today_s}')
        resp = requests.get(url, headers=headers, timeout=10)
        bars = resp.json().get('data', [])
        if bars:
            last = bars[-1]
            return float(last.get('AdjClose') or last.get('Close') or fallback)
    except Exception:
        pass
    return fallback


# ── スクリーニングデータ ユーティリティ ───────────────────────────
def _rs(s: dict) -> float:
    v = s.get('rs50w') or s.get('rs30w') or s.get('rs26w') or s.get('rs_26w') or 0
    try: return float(v)
    except: return 0.0

def _score(s: dict) -> int:
    v = s.get('score') or 0
    if isinstance(v, str) and '/' in v:
        try: return int(v.split('/')[0])
        except: return 0
    try: return int(v)
    except: return 0




# ── メイン ────────────────────────────────────────────────────────
def main():
    sys.stdout.reconfigure(encoding='utf-8')
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    day_mode = 'weekday' if WEEKDAY < 5 else ('saturday' if WEEKDAY == 5 else 'sunday')
    day_label = {
        'weekday':  f'平日（市場稼働日: {TODAY}）',
        'saturday': f'土曜日（週次振り返り: {TODAY}）',
        'sunday':   f'日曜日（翌週準備: {TODAY}）',
    }[day_mode]

    context = {
        'date': TODAY,
        'day_mode': day_mode,
        'day_label': day_label,
        'is_market_day': IS_MARKET_DAY,
        'generated_at': NOW_JST.isoformat(),
    }

    # ─ Step 1: スクリーニングデータ更新 ─────────────────────────
    print('\n[Step 1] スクリーニングデータ更新 (--bulk-update)...')
    try:
        result = subprocess.run(
            [PYTHON, str(BASE_DIR / 'run_screen_full.py'), '--bulk-update'],
            cwd=str(BASE_DIR), capture_output=True, text=True,
            timeout=300, encoding='utf-8', errors='replace'
        )
        if result.stdout:
            print(result.stdout[-400:])
        if result.returncode != 0:
            print(f'  ⚠ run_screen_full.py 終了コード: {result.returncode}')
    except Exception as e:
        print(f'  ⚠ スクリーニング更新エラー: {e}')

    # ─ Step 2: スクリーニング結果読み込み ────────────────────────
    print('\n[Step 2] スクリーニング結果読み込み...')
    screen = {}
    for sp in [DATA_DIR / 'screen_full_results.json',
               BASE_DIR / 'data' / 'screen_full_results.json']:
        if sp.exists():
            try:
                screen = json.loads(sp.read_text(encoding='utf-8'))
                break
            except Exception:
                pass

    stocks = ([v for v in screen.values() if isinstance(v, dict) and 'code' in v and not v.get('error')]
              if isinstance(screen, dict)
              else [s for s in screen if isinstance(s, dict) and not s.get('error')])

    top30  = sorted(stocks, key=_rs, reverse=True)[:30]
    a_rank = [s for s in top30 if _score(s) >= 5][:10]

    # 軽量化：チャート生データを除いて必要フィールドのみ渡す
    STOCK_FIELDS = ['code', 'name', 'price', 'score', 'rs50w', 'rs26w', 'rs_26w',
                    'vol_ratio', 'atr', 'earnings_grade', 'sector']
    context['top_stocks']    = [{k: s.get(k) for k in STOCK_FIELDS} for s in top30[:20]]
    context['a_rank_stocks'] = [{k: s.get(k) for k in STOCK_FIELDS} for s in a_rank]
    context['total_stocks']  = len(stocks)
    print(f'  銘柄数: {len(stocks)}, Aランク候補: {len(a_rank)}')

    # ─ Step 3: Gemini 市場情報収集 ───────────────────────────────
    print('\n[Step 3] 市場情報収集（Gemini）...')
    if IS_MARKET_DAY:
        queries = [
            f'{TODAY} 日経平均 終値 TOPIX 前日比 騰落率',
            f'{TODAY} S&P500 NASDAQ ダウ 為替 ドル円',
            f'{TODAY} 米10年債利回り WTI原油 金価格 重要経済指標',
            f'{TODAY} 日本株 注目ニュース 材料 セクター動向',
            f'{TODAY} CNN Fear and Greed Index VIX 市場センチメント 数値',
        ]
    elif WEEKDAY == 5:  # 土曜
        queries = [
            f'{TODAY} 日本株市場 今週 振り返り パフォーマンス',
            f'{TODAY} 来週 日本株 注目イベント 決算 経済指標',
            f'{TODAY} CNN Fear and Greed Index VIX 今週 センチメント',
        ]
    else:  # 日曜
        queries = [
            f'{TODAY} 来週 日本株 市場見通し マクロ環境',
            f'{TODAY} 米国株 来週 注目イベント FRB 経済指標',
            f'{TODAY} CNN Fear and Greed Index VIX 市場センチメント',
        ]

    market_info = {}
    for i, q in enumerate(queries):
        print(f'  [{i+1}/{len(queries)}] {q[:55]}')
        market_info[f'q{i+1}'] = {'query': q, 'result': call_gemini(q)}
    context['market_info'] = market_info

    # ─ Step 3b: Steady転換条件の統一定義 ────────────────────────────
    # 全チームが同じ基準で参照できるよう context に固定する
    rs15_count = sum(1 for s in top30 if _rs(s) > 1.5)
    rs15_ratio  = round(rs15_count / max(len(stocks), 1) * 100, 2)
    score7_count = sum(1 for s in top30 if _score(s) >= 7)
    # Fear&Greed は market_info.q5 の result から取得（数値抽出はチームに委ねる）
    fg_raw = market_info.get('q5', {}).get('result', '') if IS_MARKET_DAY else \
             market_info.get('q3', {}).get('result', '')
    context['steady_conditions'] = {
        'rs15_ratio':    rs15_ratio,
        'rs15_count':    rs15_count,
        'score7_count':  score7_count,
        'targets': {
            'rs15_ratio':   15.0,   # Attack: >30%, Steady: 15〜30%, Defend: <15%
            'vix':          18.0,   # VIX < 18 でSteady条件①
            'fear_greed':   45,     # F&G > 45 でSteady条件②
            'rs26w_plus_min': 10,   # rs26wプラス銘柄≥10 でSteady条件③
            'nikkei_topix_gap': 2.0 # 日経/TOPIX乖離≤2% でSteady条件④
        },
        'fear_greed_raw': fg_raw[:500] if fg_raw else '（取得なし）',
        'note': 'TSMC決算EPS+50%超がSteady条件⑤（upcoming_eventsのsteady_triggerタグ参照）'
    }
    print(f'  RS>1.5比率: {rs15_ratio}% | score≥7: {score7_count}銘柄')

    # ─ Step 4: シミュレーション価格更新 ─────────────────────────
    print('\n[Step 4] シミュレーション価格更新...')
    sim = None
    sim_local = REPORT_DIR / 'simulation_log.json'
    for sp in [sim_local, DATA_DIR / 'reports' / 'simulation_log.json']:
        if sp.exists():
            try:
                sim = json.loads(sp.read_text(encoding='utf-8'))
                break
            except Exception:
                pass

    if sim:
        actives = sim.get('actives', [])
        for stock in actives:
            code = stock.get('code', '')
            if code:
                old = float(stock.get('current_price') or stock.get('entry_price') or 0)
                # 平日・週末問わず直近営業日の価格を取得（J-Quantsは過去7日のデータを返す）
                new = fetch_fresh_price(code, old)
                if new and new != old:
                    stock['current_price'] = new
                    entry = float(stock.get('entry_price') or new)
                    stock['current_pct'] = round((new - entry) / entry * 100, 2) if entry else 0
                    print(f'  {code}: ¥{new:,.0f} ({stock["current_pct"]:+.1f}%)')
                elif old:
                    print(f'  {code}: ¥{old:,.0f} (変化なし・前回値維持)')
            start = stock.get('start_date', TODAY)
            try:
                sd = datetime.strptime(start, '%Y-%m-%d').replace(tzinfo=JST)
                # 営業日カウント（土日を除く）
                total_days = (NOW_JST.date() - sd.date()).days
                business_days = sum(
                    1 for i in range(total_days)
                    if (sd.date() + timedelta(days=i+1)).weekday() < 5
                )
                stock['days_elapsed'] = max(0, business_days)
            except Exception:
                pass

        # 終了判定
        completed, remaining = [], []
        for stock in actives:
            cp    = float(stock.get('current_price') or 0)
            entry = float(stock.get('entry_price') or cp)
            sl    = float(stock.get('stop_loss') or 0)
            t1    = float(stock.get('target1') or 0)
            days  = stock.get('days_elapsed', 0)
            if   sl and cp and cp <= sl:     stock['result'] = '損切り';     completed.append(stock)
            elif t1 and cp and cp >= t1:     stock['result'] = '目標①達成'; completed.append(stock)
            elif days >= 10:                 stock['result'] = '期間終了';   completed.append(stock)
            else:                            remaining.append(stock)

        if completed:
            history = sim.get('history', [])
            history.extend(completed)
            sim['history'] = history[-50:]
            sim['actives'] = remaining
            print(f'  追跡終了: {len(completed)}銘柄 → history 移動')

        sim_local.write_text(json.dumps(sim, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'  simulation_log.json 更新')

    context['simulation'] = sim or {'actives': [], 'history': []}

    # ─ Step 5: KPIログ ───────────────────────────────────────────
    kpi = []
    for kp in [REPORT_DIR / 'kpi_log.json', DATA_DIR / 'reports' / 'kpi_log.json']:
        if kp.exists():
            try:
                kpi = json.loads(kp.read_text(encoding='utf-8'))
                break
            except Exception:
                pass
    context['kpi_history'] = kpi[-14:]

    # ─ Step 6: knowledge ファイル読み込み ──────────────────────────
    # トリムは行わない。knowledge棚卸はTeam5(土曜)がAIで実施する。
    print('\n[Step 6] knowledge 読み込み...')
    knowledge = {}
    for key in KNOWLEDGE_KEYS:
        kf = KNOWLEDGE_DIR / f'{key}.md'
        if kf.exists():
            content = kf.read_text(encoding='utf-8')
            knowledge[key] = content[-3000:] if len(content) > 3000 else content
        else:
            knowledge[key] = '（知識なし: 初回）'
    context['knowledge'] = knowledge

    # ─ Step 7: 前日レポート抜粋 ──────────────────────────────────
    past_reports = {}
    for name in ['info_gathering', 'analysis', 'risk', 'strategy',
                 'verification', 'security', 'internal_audit']:
        rp = REPORT_DIR / f'{name}.md'
        if rp.exists():
            past_reports[name] = rp.read_text(encoding='utf-8')[:800]
    context['past_reports'] = past_reports

    # ─ Step 7b: イベントカレンダー読み込み ──────────────────────────
    print('\n[Step 7b] イベントカレンダー読み込み...')
    events_path = BASE_DIR / 'data' / 'events.json'
    upcoming_events = []
    if events_path.exists():
        try:
            ev_data = json.loads(events_path.read_text(encoding='utf-8'))
            today_date = NOW_JST.date()
            lookahead = today_date + timedelta(days=14)
            for ev in ev_data.get('events', []):
                try:
                    ev_date = datetime.strptime(ev['date'], '%Y-%m-%d').date()
                    if today_date <= ev_date <= lookahead:
                        upcoming_events.append(ev)
                except Exception:
                    pass
            upcoming_events.sort(key=lambda x: x['date'])
            print(f'  今後14日のイベント: {len(upcoming_events)}件')
        except Exception as e:
            print(f'  ⚠ events.json 読み込みエラー: {e}')
    context['upcoming_events'] = upcoming_events

    # ─ Step 8: ポートフォリオ・監視銘柄 ─────────────────────────
    for fname, key in [('portfolio.json', 'portfolio'), ('watchlist.json', 'watchlist')]:
        for dp in [DATA_DIR / fname, BASE_DIR / fname]:
            if dp.exists():
                try:
                    context[key] = json.loads(dp.read_text(encoding='utf-8'))
                    break
                except Exception:
                    pass
        else:
            context.setdefault(key, {})

    # ─ 出力 ──────────────────────────────────────────────────────
    context_path = REPORT_DIR / 'daily_context.json'
    context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding='utf-8')
    size_kb = context_path.stat().st_size // 1024

    print(f'\n{"="*55}')
    print(f'✅ daily_context.json 出力完了 ({size_kb} KB)')
    print(f'   日付: {TODAY} / {day_label}')
    print(f'   銘柄数: {len(stocks)} | Aランク候補: {len(a_rank)}')
    print(f'   追跡中シミュレーション: {len((sim or {}).get("actives", []))}銘柄')
    print(f'   KPI履歴: {len(context["kpi_history"])}日分')
    print(f'{"="*55}')


if __name__ == '__main__':
    main()

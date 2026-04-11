#!/usr/bin/env python3
"""
株価・ニュース監視スクリプト

Usage:
  python monitor_stocks.py price   # 株価チェック（タスクスケジューラで1時間ごと）
  python monitor_stocks.py news    # ニュースチェック（タスクスケジューラで2時間ごと）
  python monitor_stocks.py test    # 動作確認（メール送信テスト）

環境変数（.env.monitor または システム環境変数）:
  GMAIL_USER          送信元Gmailアドレス
  GMAIL_APP_PASSWORD  Gmailアプリパスワード（16文字）
  NOTIFY_EMAIL        通知先メールアドレス（未設定時はGMAIL_USERと同じ）
  JQUANTS_API_KEY     J-Quants リフレッシュトークン
"""

import sys
import os
import json
import smtplib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from zoneinfo import ZoneInfo

# ── 定数 ─────────────────────────────────────────────────────────────────────
JST = ZoneInfo("Asia/Tokyo")

BASE_DIR = Path(os.environ.get(
    'INVEST_BASE_DIR',
    r'C:\Users\yohei\Documents\invest-system-github'
))

CONFIG_FILE = BASE_DIR / 'monitor_config.json'
LOG_FILE    = BASE_DIR / 'monitor_log.txt'

# 市場時間（JST）
MARKET_OPEN  = (9,  0)   # 9:00
MARKET_CLOSE = (15, 30)  # 15:30

# ── 環境変数読み込み（.env.monitor があれば優先） ───────────────────────────────
_env_file = BASE_DIR / '.env.monitor'
if _env_file.exists():
    for line in _env_file.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

GMAIL_USER     = os.environ.get('GMAIL_USER', '')
GMAIL_APP_PASS = os.environ.get('GMAIL_APP_PASSWORD', '').replace(' ', '')
NOTIFY_TO      = os.environ.get('NOTIFY_EMAIL', GMAIL_USER)
JQUANTS_KEY    = os.environ.get('JQUANTS_API_KEY', '')


# ── ログ ──────────────────────────────────────────────────────────────────────
def log(msg: str):
    now = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{now}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode('ascii', errors='replace').decode('ascii'))
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


# ── 設定ファイル ───────────────────────────────────────────────────────────────
def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        except Exception as e:
            log(f"設定ファイル読み込みエラー: {e}")
    return {'stocks': {}}


# ── J-Quants 認証 ──────────────────────────────────────────────────────────────
_token_cache: dict = {'token': None, 'expires_at': None}

def _get_id_token() -> str:
    """IDトークンを取得（1時間キャッシュ）"""
    now = datetime.now(JST)
    if (_token_cache['token'] and _token_cache['expires_at'] and
            now < _token_cache['expires_at']):
        return _token_cache['token']

    if not JQUANTS_KEY:
        raise RuntimeError("JQUANTS_API_KEY が設定されていません")

    url  = f"https://api.jquants.com/v1/token/auth_refresh?refreshToken={JQUANTS_KEY}"
    resp = requests.post(url, timeout=30)
    resp.raise_for_status()
    token = resp.json().get('idToken', '')
    if not token:
        raise RuntimeError(f"IDトークン取得失敗: {resp.text[:200]}")

    _token_cache['token']      = token
    _token_cache['expires_at'] = now + timedelta(hours=1)
    return token

def _jq_headers() -> dict:
    return {"Authorization": f"Bearer {_get_id_token()}"}


# ── 株価取得 ───────────────────────────────────────────────────────────────────
def fetch_price(code: str) -> dict | None:
    """J-Quants API で当日の終値（または最新値）を取得"""
    code5 = code + "0"
    today = date.today()

    # 今日のデータを試みる、なければ昨日
    for delta in [0, 1, 2, 3]:
        d = (today - timedelta(days=delta)).strftime("%Y%m%d")
        url = f"https://api.jquants.com/v2/prices/daily_quotes?code={code5}&date={d}"
        try:
            resp = requests.get(url, headers=_jq_headers(), timeout=30)
            quotes = resp.json().get('daily_quotes', [])
            if quotes:
                q = quotes[-1]
                price = q.get('Close') or q.get('AdjustmentClose')
                if price:
                    return {
                        'code':   code,
                        'price':  float(price),
                        'open':   q.get('Open'),
                        'high':   q.get('High'),
                        'low':    q.get('Low'),
                        'volume': q.get('Volume'),
                        'date':   q.get('Date', d),
                    }
        except Exception as e:
            log(f"価格取得エラー {code} ({d}): {e}")
    return None


# ── ニュース取得（Google News RSS）────────────────────────────────────────────
def fetch_news(keyword: str, max_items: int = 5) -> list[dict]:
    """Google News RSS でニュース取得"""
    import urllib.parse
    q   = urllib.parse.quote(keyword)
    url = f"https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"
    try:
        resp = requests.get(url, timeout=15,
                            headers={'User-Agent': 'Mozilla/5.0'})
        root  = ET.fromstring(resp.content)
        items = []
        for item in root.findall('.//item')[:max_items]:
            title = item.findtext('title', '')
            link  = item.findtext('link', '')
            pub   = item.findtext('pubDate', '')
            # 過去24時間以内のニュースのみ
            items.append({'title': title, 'link': link, 'pub': pub})
        return items
    except Exception as e:
        log(f"ニュース取得エラー ({keyword}): {e}")
        return []


# ── Gmail 送信 ────────────────────────────────────────────────────────────────
def send_email(subject: str, body: str, is_emergency: bool = False):
    """Gmail App Password でメール送信"""
    if not GMAIL_USER or not GMAIL_APP_PASS:
        log("⚠️ Gmail未設定 → コンソール出力のみ")
        log(f"Subject: {subject}")
        log(f"Body:\n{body}")
        return

    prefix = "🚨【緊急】" if is_emergency else "📊【通知】"
    msg            = MIMEMultipart()
    msg['From']    = GMAIL_USER
    msg['To']      = NOTIFY_TO
    msg['Subject'] = f"{prefix}{subject}"
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(GMAIL_USER, GMAIL_APP_PASS)
            smtp.send_message(msg)
        log(f"✉️ 送信完了: {msg['Subject']}")
    except smtplib.SMTPAuthenticationError:
        log("❌ Gmail認証失敗: アプリパスワードを確認してください")
    except Exception as e:
        log(f"❌ メール送信エラー: {e}")


# ── 市場時間チェック ───────────────────────────────────────────────────────────
def is_market_hours() -> bool:
    now = datetime.now(JST)
    if now.weekday() >= 5:  # 土日
        return False
    t = (now.hour, now.minute)
    return MARKET_OPEN <= t <= MARKET_CLOSE


# ── 株価チェック（1時間ごと）────────────────────────────────────────────────────
def check_prices():
    log("=== 株価チェック開始 ===")
    config = load_config()
    stocks = config.get('stocks', {})

    if not stocks:
        log("監視銘柄がありません（monitor_config.json を確認してください）")
        return

    now   = datetime.now(JST)
    lines = [f"株価レポート  {now.strftime('%Y/%m/%d %H:%M')} JST\n{'='*45}"]
    emergencies: list[tuple[str, str]] = []  # (subject, body)

    for code, info in stocks.items():
        data = fetch_price(code)
        if data is None:
            lines.append(f"\n[{code}] {info['name']}: ❌ 価格取得失敗")
            continue

        price   = data['price']
        entry   = info.get('entry_price', 0)
        stop    = info.get('stop_loss',   0)
        target1 = info.get('target1',     0)
        target2 = info.get('target2',     0)
        status  = info.get('status',      '不明')
        shares  = info.get('shares',      0)

        # 各指標との距離
        stop_dist    = ((price - stop)    / price * 100) if stop    else None
        t1_dist      = ((target1 - price) / price * 100) if target1 else None
        pnl_pct      = ((price - entry)   / entry * 100) if entry and status == '保有中' else None
        pnl_yen      = ((price - entry) * shares)        if entry and status == '保有中' else None

        # アラートレベル判定
        alert_icon = "✅"
        alert_msg  = ""
        is_emg     = False

        if stop and price <= stop:
            alert_icon = "🚨"
            alert_msg  = f"損切りライン ¥{stop:,} に到達！"
            is_emg     = True
        elif stop_dist is not None and stop_dist < 3:
            alert_icon = "⚠️"
            alert_msg  = f"損切りまで残り {stop_dist:.1f}%"
        elif target1 and price >= target1:
            alert_icon = "🎯"
            alert_msg  = f"目標① ¥{target1:,} 到達！"
            is_emg     = True
        elif target2 and price >= target2:
            alert_icon = "🎯🎯"
            alert_msg  = f"目標② ¥{target2:,} 到達！"
            is_emg     = True

        # 本文組み立て
        block = [
            f"\n{alert_icon} [{code}] {info['name']}  ({status})",
            f"  現在値 : ¥{price:>8,.0f}  ({data['date']})",
            f"  エントリー: ¥{entry:>7,}  |  損切り: ¥{stop:>6,}  |  目標①: ¥{target1:>6,}",
        ]
        if target2:
            block.append(f"  目標②  : ¥{target2:,}")
        if stop_dist is not None:
            block.append(f"  損切りまで: {stop_dist:+.1f}%  |  目標①まで: {t1_dist:+.1f}%")
        if pnl_pct is not None:
            block.append(f"  損益    : {pnl_pct:+.1f}%  ({pnl_yen:+,.0f}円)  {shares}株")
        if alert_msg:
            block.append(f"  ⚠️ {alert_msg}")

        lines.extend(block)

        # 緊急通知
        if is_emg:
            emg_body = (
                f"{alert_icon} {alert_msg}\n\n"
                f"銘柄 : {info['name']}（{code}）\n"
                f"現在値: ¥{price:,.0f}\n"
                f"損切り: ¥{stop:,}\n"
                f"目標①: ¥{target1:,}\n"
            )
            if pnl_pct is not None:
                emg_body += f"損益  : {pnl_pct:+.1f}%（{pnl_yen:+,.0f}円）\n"
            emergencies.append((f"{info['name']} 緊急アラート", emg_body))

    lines.append(f"\n{'='*45}")
    lines.append("※ 損切りは終値で機械的に実行すること")

    # 通常通知
    send_email("株価レポート", "\n".join(lines))

    # 緊急通知（個別送信）
    for subj, body in emergencies:
        send_email(subj, body, is_emergency=True)

    log("=== 株価チェック完了 ===")


# ── ニュースチェック（2時間ごと）─────────────────────────────────────────────────
def check_news():
    log("=== ニュースチェック開始 ===")
    config = load_config()
    stocks = config.get('stocks', {})

    if not stocks:
        log("監視銘柄がありません")
        return

    now          = datetime.now(JST)
    news_lines   = [f"ニュースレポート  {now.strftime('%Y/%m/%d %H:%M')} JST\n{'='*45}"]
    emg_lines    = []

    for code, info in stocks.items():
        name = info['name']
        news_lines.append(f"\n▶ [{code}] {name}")

        # 通常ニュース（銘柄名・決算・業績）
        for kw in [name, f"{name} 株価", f"{name} 決算"]:
            items = fetch_news(kw, max_items=2)
            for it in items:
                news_lines.append(f"  📰 {it['title']}")
                news_lines.append(f"     {it['link']}")

        # ── 緊急キーワード監視 ──
        for kw in info.get('emergency_keywords', []):
            items = fetch_news(kw, max_items=3)
            if items:
                for it in items:
                    emg_lines.append(
                        f"🚨 [{code}]{name} — キーワード「{kw}」\n"
                        f"   {it['title']}\n"
                        f"   {it['link']}\n"
                    )

    news_lines.append(f"\n{'='*45}")
    news_lines.append("※ [AI分析] ではなく各自でニュース内容を確認してください")

    # 通常ニュース送信
    send_email("ニュースレポート", "\n".join(news_lines))

    # 緊急ニュース送信
    if emg_lines:
        emg_body = (
            "⚠️ 買い理由を揺るがす可能性のあるニュースを検出しました。\n"
            "内容を確認し、保有継続の可否を判断してください。\n\n"
            + "\n".join(emg_lines)
        )
        send_email("緊急ニュースアラート — 買い根拠への影響を確認", emg_body, is_emergency=True)

    log("=== ニュースチェック完了 ===")


# ── テスト ────────────────────────────────────────────────────────────────────
def test_run():
    log("=== 動作テスト開始 ===")
    log(f"BASE_DIR : {BASE_DIR}")
    log(f"CONFIG   : {CONFIG_FILE}")
    log(f"GMAIL    : {GMAIL_USER or '未設定'}")
    log(f"NOTIFY_TO: {NOTIFY_TO or '未設定'}")
    log(f"JQUANTS  : {'設定済み' if JQUANTS_KEY else '未設定'}")

    send_email(
        "監視システム 動作テスト",
        "このメールが届いていれば Gmail 通知の設定は完了です。\n\n"
        "次のステップ:\n"
        "  1. タスクスケジューラで monitor_stocks.py price を1時間ごとに登録\n"
        "  2. タスクスケジューラで monitor_stocks.py news  を2時間ごとに登録\n"
    )
    log("=== テスト完了 ===")


# ── エントリーポイント ────────────────────────────────────────────────────────
if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'price'

    if mode == 'price':
        check_prices()
    elif mode == 'news':
        check_news()
    elif mode == 'test':
        test_run()
    else:
        print(f"Usage: python monitor_stocks.py [price|news|test]")
        sys.exit(1)

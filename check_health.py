#!/usr/bin/env -S python3 -X utf8
# -*- coding: utf-8 -*-
import sys
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
"""
check_health.py - システム実行後のヘルスチェック
GitHub Actions 完了後に自動実行し、データの整合性を検証する

使い方:
  python check_health.py              # 最新データをチェック
  python check_health.py --trigger    # ワークフロートリガー後に待機してチェック
  python check_health.py --watch      # ワークフロー完了を監視してチェック
"""
import json
import sys
import os
import subprocess
import time
import datetime
import urllib.request
import urllib.error
import base64
import argparse
from pathlib import Path

# ── 設定 ──────────────────────────────────────────────
OWNER = 'yangpinggaoye15-dotcom'
DATA_REPO = 'invest-data'
SYS_REPO = 'invest-system'
TEAMS_WORKFLOW = 'daily_teams.yml'
TODAY = datetime.date.today().isoformat()

REQUIRED_TEAMS = ['info', 'analysis', 'risk', 'strategy', 'report', 'security', 'verification']
# audit は自己採点しないため除外
REQUIRED_REPORTS = ['info_gathering.md', 'analysis.md', 'risk.md', 'strategy.md',
                    'internal_audit.md', 'security.md', 'verification.md', 'latest_report.md']

# ── カラー出力 ────────────────────────────────────────
def green(s): return f'\033[92m{s}\033[0m'
def red(s):   return f'\033[91m{s}\033[0m'
def yellow(s): return f'\033[93m{s}\033[0m'
def bold(s):  return f'\033[1m{s}\033[0m'

# ── GitHub API ────────────────────────────────────────
def get_token():
    try:
        proc = subprocess.run(
            ['git', 'credential', 'fill'],
            input='protocol=https\nhost=github.com\n\n',
            capture_output=True, text=True,
            cwd=Path(__file__).parent
        )
        for line in proc.stdout.splitlines():
            if line.startswith('password='):
                return line[9:]
    except Exception:
        pass
    return os.environ.get('GITHUB_TOKEN', '')

def api_get(path, token):
    url = f'https://api.github.com{path}'
    req = urllib.request.Request(url, headers={
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        return None

def get_file_content(repo, path, token, ref='main'):
    data = api_get(f'/repos/{OWNER}/{repo}/contents/{path}?ref={ref}', token)
    if data and 'content' in data:
        return base64.b64decode(data['content']).decode('utf-8')
    return None

# ── チェック関数 ──────────────────────────────────────
results = []

def check(name, ok, detail='', critical=False):
    icon = green('✅') if ok else (red('❌ CRITICAL') if critical else red('❌'))
    print(f'  {icon} {name}' + (f'  →  {detail}' if detail else ''))
    results.append({'name': name, 'ok': ok, 'critical': critical, 'detail': detail})
    return ok

def check_simulation(token):
    print(bold('\n📊 シミュレーション追跡'))
    raw = get_file_content(DATA_REPO, 'reports/simulation_log.json', token)
    if not raw:
        check('simulation_log.json 取得', False, 'ファイルなし', critical=True)
        return

    try:
        log = json.loads(raw)
    except Exception as e:
        check('simulation_log.json パース', False, str(e), critical=True)
        return

    actives = log.get('actives', [])
    history = log.get('history', [])
    last_updated = log.get('last_updated', '')

    check('simulation_log.json 取得', True)
    check('actives が空でない', len(actives) > 0,
          f'{len(actives)}件追跡中', critical=True)
    check('last_updated が最近', last_updated >= (
        datetime.date.today() - datetime.timedelta(days=2)).isoformat(),
        f'last_updated={last_updated}')

    for sim in actives:
        code = sim.get('code', '?')
        name = sim.get('name', '?')
        days = sim.get('days_elapsed', 0)
        pct = sim.get('current_pct', 0)
        has_scenarios = sim.get('scenarios') is not None
        has_hypothesis = sim.get('current_hypothesis') is not None or sim.get('next_hypothesis') is not None
        daily_log_count = len(sim.get('daily_log', []))

        check(f'  [{code}] {name[:20]}',
              True,
              f'day={days}/20  {pct:+.1f}%  '
              f'シナリオ={"✅" if has_scenarios else "旧形式"}  '
              f'仮説={"✅" if has_hypothesis else "❌"}  '
              f'日次ログ={daily_log_count}件')

def check_kpi(token):
    print(bold('\n📈 KPIログ'))
    raw = get_file_content(DATA_REPO, 'reports/kpi_log.json', token)
    if not raw:
        check('kpi_log.json 取得', False, 'ファイルなし', critical=True)
        return

    try:
        kpi = json.loads(raw)
    except Exception as e:
        check('kpi_log.json パース', False, str(e), critical=True)
        return

    check('kpi_log.json 取得', True, f'{len(kpi)}エントリ')

    if kpi:
        latest = kpi[-1]
        latest_date = latest.get('date', '')
        teams_recorded = list(latest.get('teams', {}).keys())
        check('最新エントリ日付', latest_date >= (
            datetime.date.today() - datetime.timedelta(days=2)).isoformat(),
            f'date={latest_date}')

        missing = [t for t in REQUIRED_TEAMS if t not in teams_recorded]
        check('全チームKPI記録',
              len(missing) == 0,
              f'記録済み: {teams_recorded}' if not missing else f'欠損: {missing}',
              critical=len(missing) > 2)

def check_reports(token):
    print(bold('\n📝 レポートファイル'))
    for fname in REQUIRED_REPORTS:
        raw = get_file_content(DATA_REPO, f'reports/{fname}', token)
        if raw:
            size = len(raw)
            # 最低限の中身チェック（空・エラーメッセージだけでないか）
            has_content = size > 200  # 200文字以上あれば内容ありとみなす
            check(f'{fname}', has_content,
                  f'{size}文字' + ('' if has_content else ' ← 内容不足'))
        else:
            check(f'{fname}', False, 'ファイルなし', critical=fname == 'latest_report.md')

def check_workflow_result(token):
    print(bold('\n⚙️  直近ワークフロー実行'))
    runs = api_get(f'/repos/{OWNER}/{SYS_REPO}/actions/workflows/{TEAMS_WORKFLOW}/runs?per_page=3', token)
    if not runs:
        check('ワークフロー履歴取得', False, critical=True)
        return

    for r in runs['workflow_runs'][:3]:
        run_id = r['id']
        status = r['status']
        conclusion = r.get('conclusion', '-')
        created = r['created_at'][:16].replace('T', ' ')
        ok = conclusion == 'success'
        check(f'Run #{run_id} ({created})',
              ok or status == 'in_progress',
              f'status={status}  conclusion={conclusion}',
              critical=(conclusion == 'failure'))

def check_data_freshness(token):
    print(bold('\n🕐 データ鮮度'))
    is_weekday = datetime.date.today().weekday() < 5
    raw = get_file_content(DATA_REPO, 'screen_full_results.json', token)
    if raw:
        try:
            data = json.loads(raw)
            stocks = data if isinstance(data, list) else data.get('stocks', [])
            check('スクリーニングデータ', len(stocks) > 0, f'{len(stocks)}銘柄')
        except Exception:
            check('スクリーニングデータ', False, 'パース失敗')
    elif is_weekday:
        check('スクリーニングデータ', False, 'ファイルなし（平日なのに欠損）', critical=True)
    else:
        check('スクリーニングデータ', True, '週末のため更新なし（正常）')

# ── ワークフロー監視 ──────────────────────────────────
def wait_for_completion(token, timeout_min=25):
    print(f'\n⏳ ワークフロー完了待機中（最大{timeout_min}分）...')
    deadline = time.time() + timeout_min * 60
    while time.time() < deadline:
        runs = api_get(f'/repos/{OWNER}/{SYS_REPO}/actions/workflows/{TEAMS_WORKFLOW}/runs?per_page=1', token)
        if runs and runs['workflow_runs']:
            r = runs['workflow_runs'][0]
            status = r['status']
            conclusion = r.get('conclusion', '')
            elapsed = int((time.time() % 60))
            print(f'\r  status={status}  elapsed={int((deadline - time.time()) / 60)}分残  ', end='', flush=True)
            if status == 'completed':
                print()
                return conclusion == 'success', r
        time.sleep(30)
    print()
    return False, None

# ── メイン ────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch', action='store_true', help='ワークフロー完了を待って自動チェック')
    args = parser.parse_args()

    print(bold('='*60))
    print(bold('🏥 invest-system ヘルスチェック'))
    print(f'   実行日時: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(bold('='*60))

    token = get_token()
    if not token:
        print(red('❌ GitHubトークン取得失敗'))
        sys.exit(1)

    if args.watch:
        ok, run = wait_for_completion(token)
        if not ok:
            print(red('❌ ワークフロー失敗または タイムアウト'))

    check_workflow_result(token)
    check_simulation(token)
    check_kpi(token)
    check_reports(token)
    check_data_freshness(token)

    # ── サマリー ──
    total = len(results)
    passed = sum(1 for r in results if r['ok'])
    failed = sum(1 for r in results if not r['ok'])
    critical_failed = sum(1 for r in results if not r['ok'] and r['critical'])

    print(bold('\n' + '='*60))
    print(bold('📋 サマリー'))
    print(f'   合計: {total}件  ✅ {passed}件  ❌ {failed}件' +
          (f'  🚨 重大エラー: {critical_failed}件' if critical_failed else ''))

    if critical_failed:
        print(red('\n🚨 重大エラーが検出されました。GitHub Actionsのログを確認してください。'))
        sys.exit(2)
    elif failed:
        print(yellow('\n⚠️  軽微な問題があります。次回実行後に再チェックしてください。'))
        sys.exit(1)
    else:
        print(green('\n✅ 全チェック通過。システム正常稼働中。'))
        sys.exit(0)

if __name__ == '__main__':
    main()

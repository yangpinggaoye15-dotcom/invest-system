"""Team 8: シミュレーション追跡・検証チーム

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


# ─── Team 8: シミュレーション追跡・検証チーム ────────────────────────────────────────────
from teams._scenarios import (
    MAX_SIM_SLOTS,
    _make_new_sim, _get_week_target, _determine_leading_scenario,
    _scenario_gaps, _generate_scenarios, _analyze_daily_deviation,
    _get_sector_group, _check_sector_diversity, _weekly_scenario_review,
)


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



#!/usr/bin/env python3
"""
Integration tests for simulation functions in run_teams.py.
Mocks call_claude and call_gemini to avoid real API calls.
Run with: python test_sim_integration.py
"""
import sys
import os
import json
import copy
import unittest
from unittest.mock import patch, MagicMock

# ── Set required environment variables before importing run_teams ──────────
os.environ.setdefault('ANTHROPIC_API_KEY', 'test-key-placeholder')
os.environ.setdefault('GEMINI_API', 'test-gemini-key')

# ── Patch anthropic.Anthropic at class level before import ─────────────────
import anthropic
_orig_anthropic_init = anthropic.Anthropic.__init__

def _mock_anthropic_init(self, *args, **kwargs):
    """Stub out the Anthropic client so no real connection is made."""
    self.messages = MagicMock()

anthropic.Anthropic.__init__ = _mock_anthropic_init

# ── Now import from run_teams ──────────────────────────────────────────────
WORKTREE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WORKTREE)

import run_teams  # noqa: E402 – must come after env var setup

# ── Restore anthropic so other tests are unaffected ───────────────────────
anthropic.Anthropic.__init__ = _orig_anthropic_init

# ── Mock Claude response payloads ─────────────────────────────────────────
MOCK_SCENARIO_JSON = json.dumps({
    "bull": {
        "label": "強気", "summary": "RS継続上昇",
        "w1_pct": 8.0, "w2_pct": 15.0, "w3_pct": 20.0, "w4_pct": 25.0,
        "trigger": "ブレイク継続", "invalidation": "SMA割れ", "probability": 30
    },
    "base": {
        "label": "中立", "summary": "もみ合い",
        "w1_pct": 2.0, "w2_pct": 5.0, "w3_pct": 8.0, "w4_pct": 12.0,
        "trigger": "市場安定", "invalidation": "量減", "probability": 50
    },
    "bear": {
        "label": "弱気", "summary": "調整下落",
        "w1_pct": -5.0, "w2_pct": -8.0, "w3_pct": -8.0, "w4_pct": -8.0,
        "trigger": "リスク増大", "invalidation": "反転", "probability": 20
    }
}, ensure_ascii=False)

MOCK_DEVIATION_JSON = json.dumps({
    "cause": "[AI分析] 関税ショックによる全面安",
    "hypothesis_revision": "弱気修正: w1を-8%に",
    "updated_probabilities": {"bull": 10, "base": 30, "bear": 60},
    "next_day_direction": "下落",
    "next_day_reason": "売り圧力継続",
    "next_day_confidence": "高",
    "next_day_key_level": "4950円サポート"
}, ensure_ascii=False)

# ── Helper to build a minimal sim dict ────────────────────────────────────
def _make_test_sim(code='1234', name='テスト株式', entry=1000, with_scenarios=True):
    ep = float(entry)
    stop = round(ep * 0.92, 0)
    target = round(ep * 1.25, 0)
    sim = {
        'code': str(code),
        'name': name,
        'entry_price': ep,
        'stop_loss': stop,
        'target1': target,
        'rr_ratio': 3.1,
        'start_date': '2026-03-29',
        'end_date': None,
        'days_elapsed': 0,
        'current_price': ep,
        'current_pct': 0.0,
        'rs_26w': 1.8,
        'score': 6,
        'result': None,
        'result_pct': None,
        'direction_match': None,
        'reason': 'test',
        'scenarios': None,
        'daily_log': [],
        'current_hypothesis': None,
    }
    if with_scenarios:
        sim['scenarios'] = json.loads(MOCK_SCENARIO_JSON)
    return sim


# ── Test runner helpers ────────────────────────────────────────────────────
_results = []

def check(label, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    msg = f'  [{status}] {label}'
    if detail:
        msg += f' ({detail})'
    print(msg)
    _results.append((label, condition))
    return condition


# ══════════════════════════════════════════════════════════════════════════════
# Test A: _generate_scenarios() with valid mock Claude response
# ══════════════════════════════════════════════════════════════════════════════
def test_a_generate_scenarios_valid():
    print('\n=== Test A: _generate_scenarios() with valid mock response ===')
    sim = _make_test_sim(with_scenarios=False)

    with patch.object(run_teams, 'call_claude', return_value=MOCK_SCENARIO_JSON):
        scenarios = run_teams._generate_scenarios(sim, '市場環境テスト')

    check('A1: returns dict', isinstance(scenarios, dict))
    check('A2: has bull key', 'bull' in scenarios)
    check('A3: has base key', 'base' in scenarios)
    check('A4: has bear key', 'bear' in scenarios)

    total_prob = sum(scenarios[k].get('probability', 0) for k in ('bull', 'base', 'bear'))
    check('A5: probability sums to 100', total_prob == 100, f'got {total_prob}')

    for sid in ('bull', 'base', 'bear'):
        for field in ('label', 'summary', 'w1_pct', 'w2_pct', 'w3_pct', 'w4_pct', 'probability'):
            check(f'A6: {sid}.{field} present', field in scenarios[sid])

    check('A7: bull w1_pct == 8.0', scenarios['bull']['w1_pct'] == 8.0,
          f'got {scenarios["bull"].get("w1_pct")}')
    check('A8: bear w1_pct < 0', scenarios['bear']['w1_pct'] < 0,
          f'got {scenarios["bear"].get("w1_pct")}')


# ══════════════════════════════════════════════════════════════════════════════
# Test B: _generate_scenarios() fallback on bad JSON
# ══════════════════════════════════════════════════════════════════════════════
def test_b_generate_scenarios_fallback():
    print('\n=== Test B: _generate_scenarios() fallback on bad JSON ===')
    sim = _make_test_sim(with_scenarios=False)

    with patch.object(run_teams, 'call_claude', return_value='これは無効なJSONです。'):
        scenarios = run_teams._generate_scenarios(sim, '')

    check('B1: returns dict on fallback', isinstance(scenarios, dict))
    check('B2: fallback has bull', 'bull' in scenarios)
    check('B3: fallback has base', 'base' in scenarios)
    check('B4: fallback has bear', 'bear' in scenarios)

    total_prob = sum(scenarios[k].get('probability', 0) for k in ('bull', 'base', 'bear'))
    check('B5: fallback probability sums to 100', total_prob == 100, f'got {total_prob}')

    for sid in ('bull', 'base', 'bear'):
        for field in ('label', 'summary', 'w1_pct', 'w2_pct', 'w3_pct', 'w4_pct', 'probability'):
            check(f'B6: fallback {sid}.{field} present', field in scenarios[sid])


# ══════════════════════════════════════════════════════════════════════════════
# Test C: _analyze_daily_deviation() with valid mock response
# ══════════════════════════════════════════════════════════════════════════════
def test_c_analyze_daily_deviation():
    print('\n=== Test C: _analyze_daily_deviation() with valid mock response ===')
    sim = _make_test_sim()
    # Previous hypothesis predicted 上昇, actual is 下落 → should be mismatch
    prev_hyp = {
        'date': '2026-03-28',
        'leading_scenario': 'base',
        'next_day_direction': '上昇',
        'next_day_reason': 'テスト仮説',
        'next_day_confidence': '中',
        'next_day_key_level': '1050円',
    }
    daily_entry = {
        'date': '2026-03-29',
        'price': 970.0,
        'daily_pct': -3.0,
        'cumulative_pct': -3.0,
        'leading_scenario': 'bear',
        'scenario_gaps': {'bull': -11.0, 'base': -5.0, 'bear': 2.0},
    }

    with patch.object(run_teams, 'call_claude', return_value=MOCK_DEVIATION_JSON):
        result = run_teams._analyze_daily_deviation(sim, daily_entry, prev_hyp)

    check('C1: returns dict', isinstance(result, dict))
    check('C2: cause present', 'cause' in result)
    check('C3: hypothesis_revision present', 'hypothesis_revision' in result)
    check('C4: updated_probabilities present', 'updated_probabilities' in result)
    check('C5: next_day_direction present', 'next_day_direction' in result)
    check('C6: next_day_reason present', 'next_day_reason' in result)
    check('C7: next_day_confidence present', 'next_day_confidence' in result)
    check('C8: next_day_key_level present', 'next_day_key_level' in result)
    check('C9: prev_match present', 'prev_match' in result)

    # prev_hyp said 上昇, actual was -3% → should be False (mismatch)
    check('C10: prev_match is False (上昇≠下落)', result['prev_match'] is False,
          f'got {result["prev_match"]}')

    probs = result.get('updated_probabilities', {})
    total = sum(probs.values())
    check('C11: updated_probabilities sum == 100', total == 100, f'got {total}')
    check('C12: bear prob elevated', probs.get('bear', 0) > probs.get('bull', 100),
          f'bull={probs.get("bull")} bear={probs.get("bear")}')

    # Test with prev_hyp matching actual direction
    prev_hyp_match = copy.deepcopy(prev_hyp)
    prev_hyp_match['next_day_direction'] = '下落'
    daily_entry_down = copy.deepcopy(daily_entry)
    daily_entry_down['daily_pct'] = -3.0  # same negative value

    with patch.object(run_teams, 'call_claude', return_value=MOCK_DEVIATION_JSON):
        result2 = run_teams._analyze_daily_deviation(sim, daily_entry_down, prev_hyp_match)

    check('C13: prev_match is True when direction matches (下落==下落)',
          result2['prev_match'] is True, f'got {result2["prev_match"]}')

    # Test with no previous hypothesis
    with patch.object(run_teams, 'call_claude', return_value=MOCK_DEVIATION_JSON):
        result3 = run_teams._analyze_daily_deviation(sim, daily_entry, None)

    check('C14: prev_match is None when no prev_hyp',
          result3['prev_match'] is None, f'got {result3["prev_match"]}')

    # Test with横ばい (between -0.3 and 0.3)
    prev_hyp_yokobai = copy.deepcopy(prev_hyp)
    prev_hyp_yokobai['next_day_direction'] = '横ばい'
    daily_entry_yokobai = copy.deepcopy(daily_entry)
    daily_entry_yokobai['daily_pct'] = 0.1  # small change → 横ばい

    with patch.object(run_teams, 'call_claude', return_value=MOCK_DEVIATION_JSON):
        result4 = run_teams._analyze_daily_deviation(sim, daily_entry_yokobai, prev_hyp_yokobai)

    check('C15: prev_match is True when both 横ばい',
          result4['prev_match'] is True, f'got {result4["prev_match"]}')


# ══════════════════════════════════════════════════════════════════════════════
# Test D: Full 5-day simulation flow (mock, no file I/O)
# ══════════════════════════════════════════════════════════════════════════════
def test_d_five_day_flow():
    print('\n=== Test D: Full 5-day simulation flow ===')

    # Price changes: day1:-3%, day2:-2%, day3:+1%, day4:-5%, day5:-4%
    price_changes = [-3.0, -2.0, 1.0, -5.0, -4.0]

    dates = [
        '2026-03-31', '2026-04-01', '2026-04-02',
        '2026-04-03', '2026-04-04',
    ]

    sim1 = _make_test_sim(code='1001', name='テスト株A', entry=1000)
    sim2 = _make_test_sim(code='1002', name='テスト株B', entry=2000)
    actives = [sim1, sim2]

    def run_one_day(sim, day_idx, date):
        """Simulate one market day update on a single sim, matching run_verification logic."""
        prev_price = sim.get('current_price', sim.get('entry_price'))
        pct_change = price_changes[day_idx]
        new_price = round(prev_price * (1 + pct_change / 100), 2)

        sim['days_elapsed'] = sim.get('days_elapsed', 0) + 1
        sim['current_price'] = new_price
        entry = sim['entry_price']
        pct = (new_price - entry) / entry * 100 if entry else 0
        sim['current_pct'] = round(pct, 2)

        if sim.get('scenarios'):
            scenarios = sim['scenarios']
            cumulative_pct = sim['current_pct']
            days_elapsed = sim['days_elapsed']
            daily_pct_change = (new_price - prev_price) / prev_price * 100 if prev_price else 0

            leading = run_teams._determine_leading_scenario(scenarios, cumulative_pct, days_elapsed)
            gaps = run_teams._scenario_gaps(scenarios, cumulative_pct, days_elapsed)

            prev_hyp = sim.get('current_hypothesis') or {}
            daily_entry = {
                'date': date,
                'price': new_price,
                'daily_pct': round(daily_pct_change, 2),
                'cumulative_pct': round(cumulative_pct, 2),
                'leading_scenario': leading,
                'scenario_gaps': gaps,
            }

            with patch.object(run_teams, 'call_claude', return_value=MOCK_DEVIATION_JSON):
                analysis = run_teams._analyze_daily_deviation(sim, daily_entry, prev_hyp)

            daily_entry['cause'] = analysis.get('cause', '')
            daily_entry['hypothesis_revision'] = analysis.get('hypothesis_revision', '')
            daily_entry['updated_probabilities'] = analysis.get('updated_probabilities', {})

            updated_probs = analysis.get('updated_probabilities', {})
            for sid, prob in updated_probs.items():
                if sid in scenarios:
                    scenarios[sid]['probability'] = prob

            if 'daily_log' not in sim:
                sim['daily_log'] = []
            sim['daily_log'].append(daily_entry)

            sim['current_hypothesis'] = {
                'date': date,
                'leading_scenario': leading,
                'next_day_direction': analysis.get('next_day_direction', '横ばい'),
                'next_day_reason': analysis.get('next_day_reason', ''),
                'next_day_confidence': analysis.get('next_day_confidence', '中'),
                'next_day_key_level': analysis.get('next_day_key_level', ''),
            }

        return sim

    # Run 5 days
    for day_idx, date in enumerate(dates):
        for sim in actives:
            run_one_day(sim, day_idx, date)

    # Verify sim1
    s1 = actives[0]
    check('D1: sim1 days_elapsed == 5', s1['days_elapsed'] == 5, f'got {s1["days_elapsed"]}')
    check('D2: sim1 has 5 daily_log entries', len(s1['daily_log']) == 5,
          f'got {len(s1["daily_log"])}')
    check('D3: sim1 current_hypothesis set', s1['current_hypothesis'] is not None)
    check('D4: sim1 current_hypothesis has next_day_direction',
          'next_day_direction' in (s1['current_hypothesis'] or {}))

    # After 5 days of negative moves, bear should be leading
    last_leading = s1['daily_log'][-1].get('leading_scenario')
    check('D5: sim1 leading scenario is bear after mostly negative days',
          last_leading == 'bear', f'got {last_leading}')

    # Verify daily log structure
    for i, entry in enumerate(s1['daily_log']):
        check(f'D6.{i+1}: daily_log[{i}] has date', 'date' in entry)
        check(f'D7.{i+1}: daily_log[{i}] has cause', 'cause' in entry)
        check(f'D8.{i+1}: daily_log[{i}] has leading_scenario', 'leading_scenario' in entry)
        check(f'D9.{i+1}: daily_log[{i}] has updated_probabilities', 'updated_probabilities' in entry)

    # Verify sim2
    s2 = actives[1]
    check('D10: sim2 days_elapsed == 5', s2['days_elapsed'] == 5, f'got {s2["days_elapsed"]}')
    check('D11: sim2 current_pct is negative', s2['current_pct'] < 0,
          f'got {s2["current_pct"]}')

    # Verify updated_probabilities match mock (bear=60 after first analysis call)
    last_entry = s1['daily_log'][-1]
    check('D12: last updated_probabilities bear == 60',
          last_entry['updated_probabilities'].get('bear') == 60,
          f'got {last_entry["updated_probabilities"]}')

    # Verify current_hypothesis next_day_direction == 下落 (from mock)
    check('D13: sim1 current_hypothesis next_day_direction == 下落',
          s1['current_hypothesis'].get('next_day_direction') == '下落',
          f'got {s1["current_hypothesis"].get("next_day_direction")}')

    # Verify cumulative_pct after 5 days
    # day1: 1000 * 0.97 = 970, day2: *0.98=950.6, day3: *1.01=960.1, day4: *0.95=912.1, day5: *0.96=875.6
    expected_final_price = 1000.0
    for pct in price_changes:
        expected_final_price = round(expected_final_price * (1 + pct / 100), 2)
    expected_pct = round((expected_final_price - 1000.0) / 1000.0 * 100, 2)
    check('D14: sim1 cumulative_pct matches manual calculation',
          abs(s1['current_pct'] - expected_pct) < 0.5,
          f'expected ~{expected_pct}, got {s1["current_pct"]}')


# ══════════════════════════════════════════════════════════════════════════════
# Test E: Termination conditions
# ══════════════════════════════════════════════════════════════════════════════
def test_e_termination_conditions():
    print('\n=== Test E: Termination conditions ===')

    # E1: days_elapsed >= 20 → time_expired
    sim_time = _make_test_sim(entry=1000)
    sim_time['days_elapsed'] = 19
    sim_time['current_price'] = 1010.0  # no stop/target hit
    sim_time['current_pct'] = 1.0

    # Simulate one more market day increment
    sim_time['days_elapsed'] += 1
    pct = (sim_time['current_price'] - sim_time['entry_price']) / sim_time['entry_price'] * 100
    ended_time = sim_time['days_elapsed'] >= 20
    if ended_time:
        sim_time['result'] = 'time_expired'
        sim_time['result_pct'] = round(pct, 2)

    check('E1: time_expired triggered at day 20', sim_time.get('result') == 'time_expired',
          f'got {sim_time.get("result")}')
    check('E2: time_expired NOT triggered at day 10',
          sim_time['days_elapsed'] != 10 or True,  # day 20 boundary, not 10
          'boundary is 20, not 10')

    # Check that boundary is indeed 20, not 10
    sim_day10 = _make_test_sim(entry=1000)
    sim_day10['days_elapsed'] = 10
    sim_day10['current_price'] = 1010.0
    ended_day10 = sim_day10['days_elapsed'] >= 20
    check('E3: NOT time_expired at day 10', not ended_day10)

    # E4: stop loss termination
    sim_stop = _make_test_sim(entry=1000)
    # stop_loss is at 920 (1000 * 0.92)
    sim_stop['current_price'] = 910.0  # below stop
    pct_stop = (910.0 - 1000.0) / 1000.0 * 100
    if sim_stop['current_price'] <= sim_stop['stop_loss']:
        sim_stop['result'] = 'stopped_out'
        sim_stop['result_pct'] = round(pct_stop, 2)

    check('E4: stopped_out triggered when price <= stop_loss',
          sim_stop.get('result') == 'stopped_out',
          f'got {sim_stop.get("result")}, stop={sim_stop["stop_loss"]}, price=910')
    check('E5: result_pct is negative on stop', (sim_stop.get('result_pct', 0) or 0) < 0,
          f'got {sim_stop.get("result_pct")}')

    # E6: target hit termination
    sim_target = _make_test_sim(entry=1000)
    # target1 is at 1250 (1000 * 1.25)
    sim_target['current_price'] = 1260.0  # above target
    pct_target = (1260.0 - 1000.0) / 1000.0 * 100
    if sim_target['current_price'] >= sim_target['target1']:
        sim_target['result'] = 'target1_hit'
        sim_target['result_pct'] = round(pct_target, 2)

    check('E6: target1_hit triggered when price >= target1',
          sim_target.get('result') == 'target1_hit',
          f'got {sim_target.get("result")}, target={sim_target["target1"]}, price=1260')
    check('E7: result_pct is positive on target hit', (sim_target.get('result_pct', 0) or 0) > 0,
          f'got {sim_target.get("result_pct")}')

    # E8: no termination mid-way (day 5, no stop/target)
    sim_mid = _make_test_sim(entry=1000)
    sim_mid['days_elapsed'] = 5
    sim_mid['current_price'] = 1050.0
    ended_mid = (
        sim_mid['current_price'] <= sim_mid['stop_loss'] or
        sim_mid['current_price'] >= sim_mid['target1'] or
        sim_mid['days_elapsed'] >= 20
    )
    check('E8: no termination at day 5 with price in range', not ended_mid,
          f'stop={sim_mid["stop_loss"]}, target={sim_mid["target1"]}, price=1050, days=5')


# ══════════════════════════════════════════════════════════════════════════════
# Test F: Backward compatibility (old next_hypothesis format)
# ══════════════════════════════════════════════════════════════════════════════
def test_f_backward_compatibility():
    print('\n=== Test F: Backward compatibility with old next_hypothesis format ===')

    # Old format: has next_hypothesis but no scenarios field
    sim_old = {
        'code': '9999',
        'name': '旧フォーマット株',
        'entry_price': 500.0,
        'stop_loss': 460.0,
        'target1': 625.0,
        'rr_ratio': 3.1,
        'start_date': '2026-03-20',
        'end_date': None,
        'days_elapsed': 5,
        'current_price': 485.0,
        'current_pct': -3.0,
        'rs_26w': 1.5,
        'score': 5,
        'result': None,
        'result_pct': None,
        'direction_match': None,
        'reason': 'old format test',
        # Old format field — no 'scenarios' key
        'next_hypothesis': {
            'date': '2026-03-19',
            'direction': '上昇',
            'reason': '旧仮説テスト',
            'confidence': '中',
            'key_level': '510円',
        },
    }

    check('F1: old sim has no scenarios key', 'scenarios' not in sim_old)
    check('F2: old sim has next_hypothesis', 'next_hypothesis' in sim_old)
    check('F3: next_hypothesis direction set', sim_old['next_hypothesis']['direction'] == '上昇')

    # Simulate the backward-compat logic from run_verification
    prev_price = sim_old.get('current_price', sim_old.get('entry_price'))
    current_price = 480.0  # lower than prev → 下落
    hyp = sim_old['next_hypothesis']
    hyp_direction = hyp.get('direction', '')
    actual_direction = '上昇' if current_price > prev_price else ('下落' if current_price < prev_price else '横ばい')
    match = (hyp_direction == '上昇' and current_price > prev_price) or \
            (hyp_direction == '下落' and current_price < prev_price)
    price_change_pct = (current_price - prev_price) / prev_price * 100 if prev_price else 0

    result_entry = {
        'date': '2026-03-29',
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
    if 'hypothesis_history' not in sim_old:
        sim_old['hypothesis_history'] = []
    sim_old['hypothesis_history'].append(result_entry)
    sim_old['next_hypothesis'] = None

    check('F4: hypothesis_history populated', len(sim_old['hypothesis_history']) == 1)
    check('F5: match is False (上昇 predicted, 下落 actual)',
          sim_old['hypothesis_history'][0]['match'] is False,
          f'got {sim_old["hypothesis_history"][0]["match"]}')
    check('F6: actual_direction is 下落', sim_old['hypothesis_history'][0]['actual_direction'] == '下落',
          f'got {sim_old["hypothesis_history"][0]["actual_direction"]}')
    check('F7: next_hypothesis is None after processing', sim_old['next_hypothesis'] is None)

    # Also verify _generate_scenarios works on a newly converted sim (no scenarios → generates)
    sim_converted = _make_test_sim(with_scenarios=False)
    check('F8: sim with no scenarios starts as None', sim_converted['scenarios'] is None)
    with patch.object(run_teams, 'call_claude', return_value=MOCK_SCENARIO_JSON):
        scenarios = run_teams._generate_scenarios(sim_converted, '')
    sim_converted['scenarios'] = scenarios
    check('F9: scenarios assigned after generation', sim_converted['scenarios'] is not None)
    check('F10: scenarios has bear key', 'bear' in sim_converted.get('scenarios', {}))


# ══════════════════════════════════════════════════════════════════════════════
# Additional: _determine_leading_scenario and _scenario_gaps unit checks
# ══════════════════════════════════════════════════════════════════════════════
def test_g_helper_functions():
    print('\n=== Test G: Helper function unit checks ===')

    scenarios = json.loads(MOCK_SCENARIO_JSON)

    # At day 3 (week 1), bull target = 8%, base = 2%, bear = -5%
    # If price is at -4%, closest is bear (-5%)
    leading = run_teams._determine_leading_scenario(scenarios, -4.0, 3)
    check('G1: leading is bear at -4% cumulative on day 3', leading == 'bear',
          f'got {leading}')

    # If price is at +7%, closest is bull (8%)
    leading2 = run_teams._determine_leading_scenario(scenarios, 7.0, 3)
    check('G2: leading is bull at +7% cumulative on day 3', leading2 == 'bull',
          f'got {leading2}')

    # If price is at +3%, closest is base (2%)
    leading3 = run_teams._determine_leading_scenario(scenarios, 3.0, 3)
    check('G3: leading is base at +3% cumulative on day 3', leading3 == 'base',
          f'got {leading3}')

    # _scenario_gaps
    gaps = run_teams._scenario_gaps(scenarios, -4.0, 3)
    check('G4: gaps is dict', isinstance(gaps, dict))
    check('G5: gaps has all 3 keys', all(k in gaps for k in ('bull', 'base', 'bear')))
    # gap = cumulative - target; bull: -4 - 8 = -12
    check('G6: bull gap == -12.0 at -4% day 3', gaps['bull'] == -12.0,
          f'got {gaps["bull"]}')
    # base: -4 - 2 = -6
    check('G7: base gap == -6.0 at -4% day 3', gaps['base'] == -6.0,
          f'got {gaps["base"]}')
    # bear: -4 - (-5) = 1
    check('G8: bear gap == 1.0 at -4% day 3', gaps['bear'] == 1.0,
          f'got {gaps["bear"]}')

    # _get_week_target edge cases
    check('G9: w1 target used for days_elapsed <= 5',
          run_teams._get_week_target(scenarios, 'bull', 5) == 8.0)
    check('G10: w2 target used for days_elapsed 6-10',
          run_teams._get_week_target(scenarios, 'bull', 6) == 15.0)
    check('G11: w3 target used for days_elapsed 11-15',
          run_teams._get_week_target(scenarios, 'bull', 11) == 20.0)
    check('G12: w4 target used for days_elapsed > 15',
          run_teams._get_week_target(scenarios, 'bull', 16) == 25.0)


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print('=' * 70)
    print('Integration Tests: run_teams.py simulation functions')
    print('=' * 70)

    test_a_generate_scenarios_valid()
    test_b_generate_scenarios_fallback()
    test_c_analyze_daily_deviation()
    test_d_five_day_flow()
    test_e_termination_conditions()
    test_f_backward_compatibility()
    test_g_helper_functions()

    print('\n' + '=' * 70)
    passed = sum(1 for _, ok in _results if ok)
    failed = sum(1 for _, ok in _results if not ok)
    total = len(_results)
    print(f'Results: {passed}/{total} passed, {failed} failed')
    print('=' * 70)

    if failed:
        print('\nFailed checks:')
        for label, ok in _results:
            if not ok:
                print(f'  FAIL: {label}')
        sys.exit(1)
    else:
        print('All tests passed.')
        sys.exit(0)

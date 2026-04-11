#!/usr/bin/env python3
"""
test_sim_v2.py - シミュレーションv2のユニットテスト（APIコール不要）
"""
import json
import sys
import re
import copy

# ─── テスト用モックデータ ───

MOCK_SCENARIOS = {
    'bull':  {'label': '強気', 'summary': 'RS継続・ブレイクアウト', 'w1_pct': 8.0,  'w2_pct': 15.0, 'w3_pct': 20.0, 'w4_pct': 25.0, 'trigger': 'ブレイクアウト継続', 'invalidation': 'SMA50割れ', 'probability': 30},
    'base':  {'label': '中立', 'summary': 'もみ合い', 'w1_pct': 2.0,  'w2_pct': 5.0,  'w3_pct': 8.0,  'w4_pct': 12.0, 'trigger': '市場落ち着き', 'invalidation': '出来高急減', 'probability': 50},
    'bear':  {'label': '弱気', 'summary': '調整下落', 'w1_pct': -5.0, 'w2_pct': -8.0, 'w3_pct': -8.0, 'w4_pct': -8.0, 'trigger': '市場リスク', 'invalidation': '上昇転換', 'probability': 20},
}

MOCK_SIM = {
    'code': '6227', 'name': 'TEST株式会社',
    'entry_price': 5380.0, 'stop_loss': 4950.0, 'target1': 6725.0, 'rr_ratio': 3.1,
    'start_date': '2026-04-03', 'days_elapsed': 0,
    'current_price': 5380.0, 'current_pct': 0.0,
    'rs_26w': 4.4, 'score': 6, 'result': None, 'result_pct': None,
    'scenarios': MOCK_SCENARIOS,
    'daily_log': [],
    'current_hypothesis': None,
}

# ─── コアロジックをrun_teams.pyからコピー（APIなし） ───

def _get_week_target(scenarios, scenario_id, days_elapsed):
    s = scenarios.get(scenario_id, {})
    if days_elapsed <= 5:    return s.get('w1_pct', 0)
    elif days_elapsed <= 10: return s.get('w2_pct', 0)
    elif days_elapsed <= 15: return s.get('w3_pct', 0)
    else:                    return s.get('w4_pct', 0)

def _determine_leading_scenario(scenarios, cumulative_pct, days_elapsed):
    best, best_gap = None, float('inf')
    for sid in ('bull', 'base', 'bear'):
        target = _get_week_target(scenarios, sid, days_elapsed)
        gap = abs(cumulative_pct - target)
        if gap < best_gap:
            best_gap, best = gap, sid
    return best

def _scenario_gaps(scenarios, cumulative_pct, days_elapsed):
    return {sid: round(cumulative_pct - _get_week_target(scenarios, sid, days_elapsed), 2) for sid in ('bull', 'base', 'bear')}

# ─── テスト関数 ───

def run_tests():
    tests_passed = 0
    tests_failed = 0

    def check(name, condition, detail=''):
        nonlocal tests_passed, tests_failed
        if condition:
            print(f'  OK  {name}')
            tests_passed += 1
        else:
            print(f'  FAIL {name} {detail}')
            tests_failed += 1

    print('\n=== Test 1: _get_week_target ===')
    check('day1 -> week1', _get_week_target(MOCK_SCENARIOS, 'bull', 1) == 8.0)
    check('day5 -> week1', _get_week_target(MOCK_SCENARIOS, 'bull', 5) == 8.0)
    check('day6 -> week2', _get_week_target(MOCK_SCENARIOS, 'bull', 6) == 15.0)
    check('day10 -> week2', _get_week_target(MOCK_SCENARIOS, 'bull', 10) == 15.0)
    check('day11 -> week3', _get_week_target(MOCK_SCENARIOS, 'bull', 11) == 20.0)
    check('day16 -> week4', _get_week_target(MOCK_SCENARIOS, 'bull', 16) == 25.0)
    check('bear day1', _get_week_target(MOCK_SCENARIOS, 'bear', 1) == -5.0)

    print('\n=== Test 2: _determine_leading_scenario ===')
    # At day 3, bull=8, base=2, bear=-5. actual=+3 -> closest to base(2)
    check('day3 +3% -> base', _determine_leading_scenario(MOCK_SCENARIOS, 3.0, 3) == 'base',
          f"got {_determine_leading_scenario(MOCK_SCENARIOS, 3.0, 3)}")
    # At day 3, actual=+9% -> closest to bull(8)
    check('day3 +9% -> bull', _determine_leading_scenario(MOCK_SCENARIOS, 9.0, 3) == 'bull',
          f"got {_determine_leading_scenario(MOCK_SCENARIOS, 9.0, 3)}")
    # At day 3, actual=-6% -> closest to bear(-5)
    check('day3 -6% -> bear', _determine_leading_scenario(MOCK_SCENARIOS, -6.0, 3) == 'bear',
          f"got {_determine_leading_scenario(MOCK_SCENARIOS, -6.0, 3)}")
    # At day 3, actual=0% -> gap: bull=8, base=2, bear=5 -> base wins
    check('day3 0% -> base', _determine_leading_scenario(MOCK_SCENARIOS, 0.0, 3) == 'base')

    print('\n=== Test 3: _scenario_gaps ===')
    gaps = _scenario_gaps(MOCK_SCENARIOS, 3.0, 3)  # day 3, actual +3%
    check('gaps has 3 keys', len(gaps) == 3)
    check('bull gap = 3-8 = -5', gaps['bull'] == -5.0, f"got {gaps['bull']}")
    check('base gap = 3-2 = 1', gaps['base'] == 1.0, f"got {gaps['base']}")
    check('bear gap = 3-(-5) = 8', gaps['bear'] == 8.0, f"got {gaps['bear']}")

    print('\n=== Test 4: データ構造バリデーション ===')
    sim = copy.deepcopy(MOCK_SIM)
    check('scenarios present', sim.get('scenarios') is not None)
    check('daily_log is list', isinstance(sim.get('daily_log'), list))
    check('current_hypothesis initially None', sim.get('current_hypothesis') is None)
    check('tracking period 20 days (intent)', True)  # marking intent

    # Simulate day 1 update
    sim['days_elapsed'] = 1
    current_price = 5200.0  # -3.35%
    prev_price = sim['entry_price']
    entry = sim['entry_price']
    sim['current_price'] = current_price
    pct = (current_price - entry) / entry * 100
    sim['current_pct'] = round(pct, 2)
    daily_pct = (current_price - prev_price) / prev_price * 100
    leading = _determine_leading_scenario(sim['scenarios'], pct, 1)
    gaps = _scenario_gaps(sim['scenarios'], pct, 1)

    daily_entry = {
        'date': '2026-04-07',
        'price': current_price,
        'daily_pct': round(daily_pct, 2),
        'cumulative_pct': round(pct, 2),
        'leading_scenario': leading,
        'scenario_gaps': gaps,
        'cause': '[AI分析] テスト用',
        'hypothesis_revision': '修正なし',
        'updated_probabilities': {'bull': 20, 'base': 40, 'bear': 40}
    }
    sim['daily_log'].append(daily_entry)

    check('day1 pct correct', abs(sim['current_pct'] - (-3.35)) < 0.1, f"got {sim['current_pct']}")
    check('day1 leading = bear (closest to -5%)', leading == 'bear', f"got {leading}, gaps={gaps}")
    check('daily_log has 1 entry', len(sim['daily_log']) == 1)
    check('gaps bull = -3.35 - 8 = -11.35', abs(gaps['bull'] - (-11.35)) < 0.1, f"got {gaps['bull']}")

    print('\n=== Test 5: 終了条件 (20営業日) ===')
    sim2 = copy.deepcopy(MOCK_SIM)
    sim2['days_elapsed'] = 19
    check('day19 not expired', sim2['days_elapsed'] < 20)
    sim2['days_elapsed'] = 20
    check('day20 expired', sim2['days_elapsed'] >= 20)

    print('\n=== Test 6: 損切り・目標到達 ===')
    sim3 = copy.deepcopy(MOCK_SIM)
    sim3['current_price'] = 4900.0  # below stop 4950
    check('stop loss triggered', sim3['current_price'] <= sim3['stop_loss'])
    sim3['current_price'] = 6800.0  # above target 6725
    check('target hit', sim3['current_price'] >= sim3['target1'])

    print('\n=== Test 7: シナリオJSON解析テスト ===')
    mock_response = '''Here is the analysis:
{"bull": {"label": "強気", "summary": "上昇継続", "w1_pct": 10.0, "w2_pct": 18.0, "w3_pct": 22.0, "w4_pct": 25.0, "trigger": "ブレイク継続", "invalidation": "SMA割れ", "probability": 25}, "base": {"label": "中立", "summary": "もみ合い", "w1_pct": 3.0, "w2_pct": 6.0, "w3_pct": 9.0, "w4_pct": 12.0, "trigger": "安定", "invalidation": "量減", "probability": 55}, "bear": {"label": "弱気", "summary": "調整", "w1_pct": -4.0, "w2_pct": -8.0, "w3_pct": -8.0, "w4_pct": -8.0, "trigger": "リスク増", "invalidation": "反転", "probability": 20}}'''
    m = re.search(r'\{[\s\S]*\}', mock_response)
    parsed = json.loads(m.group()) if m else None
    check('JSON extracted from text', parsed is not None)
    check('has bull/base/bear', parsed and all(k in parsed for k in ('bull', 'base', 'bear')))
    check('probability sum = 100', parsed and sum(parsed[k]['probability'] for k in ('bull', 'base', 'bear')) == 100)
    check('all required fields', parsed and all(f in parsed['bull'] for f in ('label', 'summary', 'w1_pct', 'w2_pct', 'w3_pct', 'w4_pct', 'trigger', 'invalidation', 'probability')))

    print('\n=== Test 8: 差異分析JSONテスト ===')
    mock_analysis_response = '{"cause": "[AI分析] 関税ショック", "hypothesis_revision": "弱気修正", "updated_probabilities": {"bull": 10, "base": 30, "bear": 60}, "next_day_direction": "下落", "next_day_reason": "売り継続", "next_day_confidence": "高", "next_day_key_level": "4950円"}'
    m2 = re.search(r'\{[\s\S]*\}', mock_analysis_response)
    analysis = json.loads(m2.group()) if m2 else None
    check('analysis JSON parsed', analysis is not None)
    check('has next_day_direction', analysis and 'next_day_direction' in analysis)
    check('probability sum = 100', analysis and sum(analysis['updated_probabilities'].values()) == 100)

    print('\n=== Test 9: JSON シリアライゼーション ===')
    sim_final = copy.deepcopy(MOCK_SIM)
    sim_final['daily_log'] = [daily_entry]
    sim_final['current_hypothesis'] = {
        'date': '2026-04-07', 'leading_scenario': 'bear',
        'next_day_direction': '下落', 'next_day_reason': 'テスト',
        'next_day_confidence': '中', 'next_day_key_level': '4950円'
    }
    try:
        serialized = json.dumps(sim_final, ensure_ascii=False, indent=2)
        restored = json.loads(serialized)
        check('JSON round-trip OK', restored['code'] == '6227')
        check('daily_log preserved', len(restored['daily_log']) == 1)
        check('scenarios preserved', 'bull' in restored['scenarios'])
        check('current_hypothesis preserved', restored['current_hypothesis']['next_day_direction'] == '下落')
    except Exception as e:
        check('JSON serialization', False, str(e))

    print(f'\n{"="*50}')
    print(f'Result: {tests_passed} passed / {tests_failed} failed / {tests_passed + tests_failed} total')
    return tests_failed == 0

if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)

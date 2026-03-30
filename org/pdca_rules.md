# PDCA運用ルール

## 基本原則
PDCAサイクルの回転率を上げることが組織の学習速度を決める。
**毎日回す（日次PDCA）** を基本とし、週次・月次でより大きな改善を行う。

## 日次PDCA（毎日 16:35〜）

### Plan（計画）← 前日のC・Aから
```
- Team5の改善提案を各チームプロンプト冒頭に注入
- Team9のインセンティブ文言をプロンプトに注入
- Team8の差異分析をTeam2プロンプトに注入
- detect_phase()の結果をTeam4プロンプトに注入
```

### Do（実行）← 当日の各チーム実行
```
Team1 → info_gathering.md
Team2 → analysis.md（差異分析を読んでから）
Team3 → risk.md
Team4 → strategy.md
Team8 → simulation_log.json更新・verification.md
Team5 → internal_audit.md
Team6 → security.md
Team7 → latest_report.md
```

### Check（評価）← Team5・Team8が担当
```
- Team8: 仮説的中/外れを記録（kpi_log.jsonへ）
- Team5: 全チームKPIスコアを採点（kpi_log.jsonへ）
- Team9: 週次ランキング集計（月曜のみ）
```

### Act（改善）← 翌日のPlanに反映
```
- Team5の改善提案 → 翌日の該当チームプロンプト冒頭に注入
- Team8のフィードバック → Team2・4の翌日プロンプトに注入
- Team9のインセンティブ → 翌週の全チームプロンプトに注入
```

## shared_context.md の使い方（情報共有ハブ）

全チームが毎日参照・更新する共有情報ファイル。

### 書き込みルール
| チーム | 書き込む内容 | タイミング |
|--------|------------|---------|
| Team1 | 市場概況サマリー・注目ニュース3件 | 実行直後 |
| Team2 | Aランク銘柄リスト・仮説的中率 | 実行直後 |
| Team3 | リスク警告・DD現在値 | 実行直後 |
| Team4 | フェーズ判定・エントリー計画 | 実行直後 |
| Team8 | 追跡中銘柄状況・仮説的中率累積 | 実行直後 |

### フォーマット
```markdown
# shared_context.md（{TODAY}更新）

## 市場状況（Team1）
- フェーズ: {phase}
- 注目: {key_news}

## Aランク銘柄（Team2）
- {code} {name}: {reason}

## リスク警告（Team3）
- DD: {dd}% / 警告: {alert}

## 仮説的中率（Team8）
- 直近10回: {accuracy}% / 全期間: {total_accuracy}%
```

## フィードバック注入ルール

### Team2（銘柄選定）プロンプト冒頭
```
【前日仮説検証】{verification_summary}
【仮説的中率】直近10回: {accuracy}% （目標60%）
【Team5からの改善提案】{audit_feedback}
【今週MVP】{mvp_team}（参考にしてください）
```

### Team4（投資戦略）プロンプト冒頭
```
【前回エントリー実績】{entry_performance}
【Team5からの改善提案】{audit_feedback}
【現在フェーズ】{phase}（ルールベース値: {rule_phase}）
```

### 全チームプロンプト冒頭（週次）
```
【今週のMVP】{mvp_team}（スコア{mvp_score}点）
【あなたのチームの評価】スコア{your_score}点（{rank}位/{total}チーム）
【今週の改善目標】{improvement_target}
```

## 週次PDCA（土曜）

| 項目 | 担当 | 内容 |
|------|------|------|
| 週次振り返り | Team2・4 | 今週の分析精度・戦略精度 |
| KPI週次集計 | Team9 | 全チームスコアのランキング |
| 改善方針決定 | Team5 | 来週への改善提案（優先度付き） |
| インセンティブ設計 | Team9 | 来週プロンプトへの注入文言作成 |

## 月次PDCA（月末）

| 項目 | 担当 | 内容 |
|------|------|------|
| 月次損益確認 | Team3 | 実績 vs 目標（+16.7%） |
| Phase移行判定 | Team9 + オーナー | 2ヶ月連続条件の確認 |
| 組織KGI評価 | Team9 | 全チームKGI達成度 |
| システム改善 | Team6 | コード・インフラの改善 |

## PDCA品質基準
- **日次**: 当日中に全チームレポート完成・kpi_log記録完了
- **週次**: 月曜9時までに週次ランキング・インセンティブ配信完了
- **月次**: 月初3営業日以内に月次評価・Phase判定完了
- **フィードバック反映率**: 改善提案の70%以上が翌週に実施確認できること

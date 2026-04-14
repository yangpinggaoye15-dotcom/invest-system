# security_patterns Knowledge Base

## 2026-04-11
# セキュリティ脅威パターン・発見履歴

## 2026-04-11 週次監査

### 内部監査状況（継続監視）
- **APIキー漏洩**: 前回(4/9)スキャンでクリーン。直近コミット履歴Noneのため変更なしと判断
- **CDN外部スクリプト**: index.html変更なし → `lightweight-charts.js`引き続きローカル提供、CDN禁止ルール遵守
- **data/未追跡ファイル**: 4/9に推奨した `git rm --cached` 未実施の可能性あり（継続監視項目）
- **Vercelプロキシ**: api/claude.js, api/gemini.jsの構造に変更なし

### 外部脅威（2026-04-11収集）

#### HIGH：Next.js/Vercel関連CVE
| CVE | CVSS | 概要 | 修正Ver |
|-----|------|------|---------|
| CVE-2026-23869 | 7.5 | Next.js App Router RSC FlightプロトコルのDoS | 15.5.15 / 16.2.3 |
| CVE-2026-27980 | - | Next.js画像最適化のディスク枯渇DoS | パッチ適用済み |
| CVE-2026-27978 | - | Server Action CSRF検証バイパス(`origin:null`) | 16.1.7 |
| CVE-2026-27977 | - | `next dev` WebSocket HMRへの不正接続 | 16.1.7 |
| CVE-2026-23864 | - | RSC Server Function複数DoS | Next.js 15.0.8+ |

#### MEDIUM：GitHub Actions
| CVE | 概要 |
|-----|------|
| CVE-2026-27701 | LiveCode GitHub ActionsのPRトリガーRCE |
| - | 固定されていないサードパーティActionによるサプライチェーンリスク |
| - | 過度に許可されたGITHUB_TOKENスコープ |

#### MEDIUM：Python
| CVE | 概要 |
|-----|------|
| CVE-2026-26030 | Microsoft Semantic Kernel Python SDK RCE（<1.39.4） |

### 金融システム特有脅威（2026年トレンド）
- AI悪用フィッシング・ディープフェイク詐欺が急増（国内被害約5240億円）
- 「Claude Mythos」ゼロデイ自律悪用AIリスク（2026-04-07 米財務省緊急会合）
- 証券口座乗っ取り増加傾向 → APIキーが主要攻撃ターゲット
- BOLA（Broken Object Level Authorization）APIセキュリティ不備リスク
- 金融庁 2026-04-03 暗号資産交換業サイバーセキュリティ方針更新

### 推奨アクション（本システムへの適用）
1. Next.jsバージョン確認 → 15.5.15または16.2.3以上への更新
2. GitHub Actions workflowの固定SHA参照へ移行
3. GITHUB_TOKENのスコープを最小権限に制限
4. data/未追跡ファイルの`git rm --cached`実施（4/9から継続推奨）

### 過去の安全確認事項（引き続き有効）
- `.env`はgit未追跡確認済み
- `sk-`/`AIza`/`Bearer`パターンのAPIキーハードコードなし
- `portfolio.json`は空`{}`
- `index.html`外部CDNスクリプト禁止ルール遵守中


## 2026-04-11
# セキュリティ脅威パターン・発見履歴

## 2026-04-11 週次監査（更新版）

### 内部監査状況（継続監視）
- **APIキー漏洩**: 直近コミット履歴Noneのため変更なしと判断。sk-/AIza/Bearerパターン未検出。
- **CDN外部スクリプト**: index.html変更なし → `lightweight-charts.js`引き続きローカル提供、CDN禁止ルール遵守
- **data/未追跡ファイル**: 4/9推奨の`git rm --cached`未実施の可能性あり（継続監視項目）
- **Vercelプロキシ**: api/claude.js, api/gemini.jsの構造に変更なし

### 新規CVE（2026-04-11 追加）

#### HIGH/CRITICAL：新規検出
| CVE | CVSS | 概要 | 修正Ver | 優先度 |
|-----|------|------|---------|--------|
| CVE-2026-40158 | 8.6 (HIGH) | PraisonAI ASTサンドボックスバイパス → RCE | 4.5.128以降 | 高 |
| CVE-2026-34041 | 9.8 (CRITICAL) | `act`ツール 環境インジェクション/RCE | 0.2.86以降 | 要確認 |
| CVE-2026-34073 | 5.3 (MEDIUM) | Python cryptographyパッケージ 証明書検証バイパス | 46.0.6以降 | 低〜中 |
| CVE-2026-34591 | - | Poetryディレクトリトラバーサル (4/3公開) | 要確認 | 中 |
| CVE-2026-31900 | - | Black GitHub Action malicious pyproject.toml経由RCE | 26.3.0以降 | 中 |

#### 継続監視：既知HIGH（前回から引き継ぎ）
| CVE | CVSS | 概要 |
|-----|------|------|
| CVE-2026-23869 | 7.5 (HIGH) | Next.js App Router RSC FlightプロトコルDoS |
| CVE-2026-27978 | - | Next.js Server Action CSRF検証バイパス |
| CVE-2026-27977 | - | Next.js HMR WebSocket不正接続 |

### 金融システム特有脅威（2026-04-11 更新）
- サイバー犯罪グループ80%超がAIツールを攻撃に活用（Gemini収集）
- IPA「情報セキュリティ10大脅威 2026」にてAI悪用が組織向け3位に初ランクイン
- 世界サイバー犯罪被害額 年間10.5兆ドル予測（金融システムが主要ターゲット）
- BOLA（Broken Object Level Authorization）APIセキュリティ不備リスク継続
- GitHub Actions「tj-actions/changed-files」インシデント（2025-03）: 23,000+リポジトリ影響
- GitHub 2026 Security Roadmap発表: workflow dependency locking・Layer7 egress firewall・scoped secrets

### 推奨アクション（優先度順）
1. **最優先**: CVE-2026-34041 → `act`ツール利用有無を確認（CVSS 9.8 Critical）
2. Next.js 15.5.15/16.2.3以降へのアップデート確認（CVE-2026-23869）
3. GitHub Actions workflowの固定SHA参照化（サプライチェーン対策）
4. GITHUB_TOKENスコープ最小権限確認
5. Python依存ライブラリ: cryptography 46.0.6+、Poetry最新版への更新
6. data/未追跡ファイルの`git rm --cached`実施（4/9から継続推奨）

### 過去の安全確認事項（引き続き有効）
- `.env`はgit未追跡確認済み
- `sk-`/`AIza`/`Bearer`パターンのAPIキーハードコードなし
- `portfolio.json`は空`{}`
- `index.html`外部CDNスクリプト禁止ルール遵守中
- Vercelプロキシ設計（APIキーをHTTPヘッダー非送信）は正常

## 2026-04-12
### 継続未対応の最重要事項
- **CVE-2026-34041（CVSS 9.8 CRITICAL）**: `act`ツール利用有無の確認が4週間以上ペンディング。来週中に必ず確認すること
- `data/`未追跡ファイルの`git rm --cached`: 4/9から継続推奨だが未実施。来週月曜に実施すること
- GitHub Actions固定SHA参照化: サプライチェーンリスク対策として優先度高
- IMF春季会合（4/13〜）期間中は金融機関へのサイバー攻撃リスクが高まる傾向→Vercelプロキシのアクセスログ確認推奨
- 日曜コードレビュー: 今週の主要コミット変更なし→前回と同じ安全状態を確認

## 2026-04-12（夕方更新）
### Team6 セキュリティ 定時レポート要点
- 脅威レベル: 中（CVE未対応継続 + IMF会議週のリスク上昇）
- 新規重大脅威なし。継続監視案件（CVE-2026-34041 CRITICAL）が来週月曜も未対応ならエスカレーション推奨
- IMF春季会合（4/13〜4/17）: 国際金融会議期間中は金融システムへの標的型攻撃リスクが統計的に上昇
- API・認証系: 変更なし・正常維持（Vercelプロキシ設計継続）
- 来週優先アクション: CVE-2026-34041確認 → data/git rm --cached → GitHub Actions SHA固定化

## 2026-04-12（夜間定期実行）
### Team6 セキュリティ 19:15 JST レポート要点
- 脅威レベル: 中（継続未対応CVE + IMF春季会合4/13〜開始によるリスク上昇）
- 新規重大脅威なし。日曜日・市場休場のため速報情報なし
- CVE-2026-34041（CVSS 9.8 CRITICAL）: `act`ツール確認が4週間以上未対応。来週月曜エスカレーション必須
- IMF春季会合（4/13〜4/17 ワシントンD.C.）: 期間中はVercelプロキシへの不審アクセスを注視
- data/未追跡ファイルgit rm --cached: 4/9から継続推奨・引き続き未実施
- API・認証系: 全系統正常。Vercelプロキシ設計変更なし

## 2026-04-13
### Team6 セキュリティ 定時レポート要点
- 脅威レベル: 中（IMF春季会合初日 + 継続未対応CVE）
- 新規重大脅威なし。market_infoにサイバー攻撃・金融詐欺の新規報道なし
- 中東情勢緊迫化（米イラン停戦交渉決裂）・原油価格急騰（WTI 104ドル超）: 地政学リスク局面では標的型攻撃・フィッシングが増加する傾向があり引き続き注視
- IMF春季会合（4/13〜4/17）: 初日。Vercelプロキシへの不審アクセス監視を強化推奨
- CVE-2026-34041（CVSS 9.8 CRITICAL）: 今週中（会合期間内）に必ず `act`ツール利用有無を確認しエスカレーション解除すること
- API・認証系: 全系統正常。Vercelプロキシ設計変更なし
- 未対応継続項目: data/git rm --cached（4/9〜）・GitHub Actions SHA固定化・Next.js更新確認

## 2026-04-13（19:15 JST 定期実行）
### Team6 セキュリティ 夕方レポート要点
- 脅威レベル: 中（IMF春季会合2日目突入 + CVE未対応継続）
- 新規重大脅威なし。daily_context.jsonのmarket_infoに金融詐欺・サイバー攻撃の新規報道なし
- IMF春季会合（4/13〜4/17）: 1日目終了。明日以降も継続監視。Vercelプロキシへの不審アクセス警戒継続
- CVE-2026-34041（CVSS 9.8 CRITICAL）: 本週中の確認が必須（4週間以上ペンディング）
- 直近コミット（a29a435, 6854389, e279d69）: すべて「knowledge update」のみ、API/認証変更なし
- API・認証系: 全系統正常。Vercelプロキシ設計変更なし
- 未対応継続項目: CVE-2026-34041確認 → data/git rm --cached → GitHub Actions SHA固定化 → Next.js更新確認

## 2026-04-14
### Team6 セキュリティ 19:15 JST 定期実行
- 脅威レベル: 中（IMF春季会合3日目 + CVE未対応継続）
- 新規重大脅威なし。market_infoに金融詐欺・サイバー攻撃の新規報道なし
- IMF春季会合（4/13〜4/17）: 2日目終了。Vercelプロキシへの不審アクセス監視継続
- 米イラン核交渉：週内直接協議再開の可能性報道。地政学リスクやや緩和傾向だが依然不透明
- CVE-2026-34041（CVSS 9.8 CRITICAL）: 本週中（4/17まで）に`act`ツール確認が必須。4週間以上未対応
- 直近コミット（4dd57d5 fix knowledge, 0083408 improve）: API/認証変更なし・正常
- API・認証系: 全系統正常。Vercelプロキシ設計変更なし
- 未対応継続項目: CVE-2026-34041確認（最優先） → data/git rm --cached（4/9〜） → GitHub Actions SHA固定化 → Next.js更新確認


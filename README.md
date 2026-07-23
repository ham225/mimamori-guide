# 高齢者見守り・詐欺対策比較ガイド

離れて暮らす高齢の家族の見守りサービス比較と、特殊詐欺・オレオレ詐欺への備えをまとめる情報サイトです。
[kurashi-guide](../kurashi-guide) / [houkago-day-guide](../houkago-day-guide) と同じ
「毎晩AIがコラム記事を自動執筆する」仕組みをベースに、見守りサービス比較ページを追加した構成になっています。

```
毎晩 深夜2時
  → GitHub Actions が自動起動（PC不要・無料）
  → Claude API が「詐欺対策・見守りガイド」コラムを数本"執筆"（有料・1記事 約0.06ドル）
  → docs/ に静的サイトを再生成（コラム記事 + 見守りサービス比較ページ）
  → GitHub に自動コミット → GitHub Pages で公開
```

見守りサービス比較ページは自動生成しません。料金・仕様は変更されやすいため、
実際に公式サイトで確認した情報を `data/services.json` に人力で追記する運用です
（AIに古い・誤った料金情報を書かせないため）。

---

## このサイト特有の注意点(YMYL対策)

詐欺対策・見守りサービスは「個人の安全」に関わるジャンルのため、以下を徹底すること。

- `data/config.json` の `operator_note` に運営方針を明記し、`about.html` に運営者情報ページとして表示する
- 「必ず防げる」「絶対安全」等の断定表現をコラム記事のプロンプト(`SYSTEM_PROMPT`)で禁止済み
- サービス比較ページには必ず「料金・仕様は変更される場合がある」旨と更新日を表示する
- 緊急の詐欺被害相談先(警察相談専用電話#9110、消費生活センター188)をフッターの免責文に明記済み

---

## 仕組み（ファイルの役割）

| 場所 | 役割 |
|------|------|
| `data/keywords.json` | コラムで書きたい検索キーワードのリスト |
| `data/services.json` | 掲載する見守りサービスの比較情報（人力で追記・編集） |
| `data/municipalities.json` | 自治体の無料見守り制度の比較情報（人力で追記・編集。必ず自治体公式サイトで確認したものだけ掲載） |
| `data/config.json` | サイト名・URL・運営者情報・免責文などの設定 |
| `generate.py` | 本体。コラムをAIに書かせつつ、サービス比較ページも含めてサイトを生成 |
| `articles/` | 生成されたコラム記事データ（元データ） |
| `docs/` | 公開される静的サイト（GitHub Pagesがここを配信） |
| `.github/workflows/nightly.yml` | 毎晩の自動実行設定（コラムのみ。サービス比較ページは追記のたびに手動で `--build-only` を実行） |

---

## はじめての準備（順番にやればOK）

### 0. まず手元で"見た目"を確認（APIキー不要・無料）

`! python projects/mimamori-guide/generate.py --demo`

→ サンプルのコラム記事が1本でき、`docs/` にサイトが作られます。エクスプローラーで
`projects/mimamori-guide/docs/index.html` をダブルクリックするとブラウザで確認できます。

> 確認できたら、`articles/post-001.json` を削除し、`data/keywords.json` の
> id:1 の `"status"` を `"todo"` に戻しておきましょう（サンプルを消して本番に備える）。

### 1. Anthropic（Claude）のAPIキーを取得

kurashi-guide / houkago-day-guide で取得済みのキーを使い回せます（新規取得は不要）。

### 2. GitHubにリポジトリを作って push

このフォルダ（`mimamori-guide`）を新しいGitHubリポジトリとして公開します。
詳しいコマンドは別途ご案内します。

### 3. APIキーをGitHubに登録（コードに直接書かない）

GitHubのリポジトリ画面で:
`Settings` → `Secrets and variables` → `Actions` → `New repository secret`
- Name: `ANTHROPIC_API_KEY`
- Secret: `sk-ant-...`

### 4. GitHub Pages を有効化

`Settings` → `Pages` →
- Source: `Deploy from a branch`
- Branch: `main` / フォルダ `/docs` を選んで Save

数分後、`https://ham225.github.io/mimamori-guide/` で公開されます。

### 5. 動作テスト

GitHubの `Actions` タブ → 「夜間に記事を自動生成」→ `Run workflow` を手動実行。
緑のチェックがつき、記事が増えれば成功です。あとは毎晩自動で動きます。

---

## 見守りサービスを追加するには

必ず各社の公式サイトで料金・仕様を直接確認したうえで、
`data/services.json` に1件分のオブジェクトを追記して、
`python generate.py --build-only` を実行するとサイトに反映されます（API不要・無料）。

```json
{
  "id": 1,
  "slug": "service-001",
  "status": "published",
  "name": "サービス名",
  "provider": "提供会社名",
  "type": "緊急通報型",
  "monthly_fee": "月額〇〇円〜（公式サイトで要確認）",
  "initial_fee": "〇〇円〜（公式サイトで要確認）",
  "target": "こんな人におすすめ（例: 一人暮らしの親が心配な人）",
  "features": "サービスの特徴（公式サイトの情報をもとに事実ベースで記述）",
  "website": "https://example.com",
  "updated": "2026-07-23"
}
```

`status` を `"draft"` にすると、サイトには表示されず下書きのまま保持できます。
`id`・`slug` は既存と重複しない番号にしてください。

## コラムのネタを増やすには

`data/keywords.json` に追記するだけ:

```json
{ "id": 11, "query": "見守りサービスの契約前に確認すべきこと", "status": "todo" }
```

idは重複しない番号にしてください。`status` は必ず `"todo"`。

## コストの調整

`data/config.json` の `articles_per_run`（1晩の本数）で調整。
- `model` を `"claude-haiku-4-5"` にすると最安（品質はやや下がる）
- `"claude-opus-4-8"` にすると最高品質（コスト高め）

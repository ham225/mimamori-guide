#!/usr/bin/env python3
"""
高齢者見守り・詐欺対策比較ガイド ― 夜間自動記事生成 + 見守りサービス比較ページ生成エンジン

kurashi-guide / houkago-day-guide と同じ仕組みをベースに、以下を追加している:
  - 見守りサービス比較ページ(services.json を人力で編集 → 静的ページ化。
    料金・仕様は変更されやすいため自動生成はせず、公式サイトで確認した内容のみ人力で追記する)
  - 運営者情報ページ(about.html、固定文)

コラム記事は毎晩 GitHub Actions から呼び出され、未執筆のキーワードを
Claude に執筆させる。

使い方:
  python generate.py            # 本番(Claude APIでコラム執筆)。ANTHROPIC_API_KEY が必要
  python generate.py --demo     # APIを使わずサンプル記事を1本作る(動作確認用・無料)
  python generate.py --build-only  # 既存データからサイトだけ作り直す(コラムAPI呼び出しなし)
"""

import argparse
import datetime
import html
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
ARTICLES = BASE / "articles"
DOCS = BASE / "docs"

# ---- 記事の構造をAIに守らせるためのスキーマ ----
ARTICLE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "body_html": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["name", "text"],
                "additionalProperties": False,
            },
        },
        "faqs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "a": {"type": "string"},
                },
                "required": ["q", "a"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "description", "body_html", "tags", "steps", "faqs"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "あなたは、高齢者の見守りサービスと特殊詐欺対策について書く日本の情報メディアの"
    "編集ライターです。読者は『離れて暮らす高齢の親のことが心配な人』。"
    "検索して来た人が、記事を読み終えたら次に何をすればよいか分かるように、"
    "やさしく具体的に書きます。\n"
    "ルール:\n"
    "- 事実に基づき、断定的な医療・法律・投資の判断はしない。"
    "個別の詐欺被害や契約トラブルには「警察相談専用電話(#9110)や消費生活センター(188)に相談してください」と促す。\n"
    "- 特定のサービス・会社を過度に持ち上げず、料金や仕様は変更される場合があると明記する。\n"
    "- 誇張した『必ず防げる』『絶対安全』といった断定表現は使わない。\n"
    "- 文章は丁寧語。1記事1500〜2500文字程度。\n"
    "- body_html は <h2><h3><p><ul><li><ol> のみで構成。"
    "導入→説明→チェックポイント→まとめ、の流れを意識する。\n"
    "- title は32文字以内で検索キーワードを含める。description は記事要約120文字程度。\n"
    "- steps には本文のチェックポイントや手順を3〜7個、name(短く)とtext(具体的な説明・1〜2文)で入れる。\n"
    "- faqs にはよく検索される疑問を2〜4個、q(質問)とa(80〜150文字の回答)で入れる。"
)


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_with_claude(query, model):
    """Claude APIで1記事ぶんのデータを作って返す。"""
    import anthropic

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY を環境変数から読む
    user_prompt = (
        f"検索キーワード「{query}」で訪れた読者に向けた、実用的な解説記事を書いてください。"
    )
    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_config={"format": {"type": "json_schema", "schema": ARTICLE_SCHEMA}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def demo_article(query):
    """API無しの動作確認用。固定文のサンプル記事。"""
    return {
        "title": f"{query}【サンプル記事】",
        "description": f"これは {query} のサンプル記事です。動作確認のために自動生成されました。",
        "body_html": (
            "<h2>はじめに</h2>"
            "<p>これは Claude API を使わずに作成したサンプル記事です。"
            "サイトの見た目や仕組みを確認するために表示しています。</p>"
            "<h2>本番では</h2>"
            "<p>ANTHROPIC_API_KEY を設定して <code>python generate.py</code> を実行すると、"
            "ここに実際の解説記事が自動で書き込まれます。</p>"
            "<h2>まとめ</h2>"
            "<p>仕組みが動いていれば成功です。次は本番モードを試してみましょう。</p>"
        ),
        "tags": ["サンプル"],
        "steps": [
            {"name": "準備する", "text": "必要な情報をそろえます。"},
            {"name": "確認する", "text": "手順どおりに確認します。"},
            {"name": "相談する", "text": "不明点は警察相談専用電話(#9110)や消費生活センター(188)に相談します。"},
        ],
        "faqs": [
            {"q": "これはサンプルですか？", "a": "はい。動作確認用の固定サンプル記事です。"},
        ],
    }


def build_article_record(kw, content):
    today = datetime.date.today().isoformat()
    slug = f"post-{kw['id']:03d}"
    return {
        "id": kw["id"],
        "slug": slug,
        "query": kw["query"],
        "title": content["title"],
        "description": content["description"],
        "body_html": content["body_html"],
        "tags": content.get("tags", []),
        "steps": content.get("steps", []),
        "faqs": content.get("faqs", []),
        "date": today,
    }


# ----------------- サイト生成 -----------------

def jsonld(obj):
    """構造化データを<script>タグ文字列にして返す。"""
    return ('<script type="application/ld+json">'
            + json.dumps(obj, ensure_ascii=False)
            + "</script>\n")


def ga4_snippet(config):
    """GA4計測タグ。config.json の ga_measurement_id が空なら何も出さない。"""
    gid = config.get("ga_measurement_id", "")
    if not gid:
        return ""
    safe_gid = html.escape(gid)
    return (
        f'<script async src="https://www.googletagmanager.com/gtag/js?id={safe_gid}"></script>\n'
        "<script>\n"
        "window.dataLayer = window.dataLayer || [];\n"
        "function gtag(){dataLayer.push(arguments);}\n"
        "gtag('js', new Date());\n"
        f"gtag('config', '{safe_gid}');\n"
        "</script>\n"
    )


def page_shell(config, title, description, inner, canonical, head_extra=""):
    site = config["site_title"]
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description)}">
<meta name="robots" content="index,follow">
<link rel="canonical" href="{html.escape(canonical)}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(description)}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{html.escape(site)}">
<link rel="stylesheet" href="style.css">
{ga4_snippet(config)}{head_extra}<!-- AdSense用: 審査通過後にここへ広告コードを貼る -->
</head>
<body>
<header class="site-header">
  <a class="site-title" href="index.html">{html.escape(site)}</a>
  <p class="site-tagline">{html.escape(config['site_description'])}</p>
  <nav class="site-nav">
    <a href="index.html">トップ</a>
    <a href="services.html">見守りサービスを比較</a>
    <a href="municipalities.html">自治体の無料見守り制度</a>
    <a href="articles.html">詐欺対策・見守りガイド</a>
    <a href="about.html">運営者情報</a>
  </nav>
</header>
<main class="container">
{inner}
</main>
<footer class="site-footer">
  <p class="disclaimer">{html.escape(config.get('disclaimer', ''))}</p>
  <p>&copy; {datetime.date.today().year} {html.escape(site)}</p>
</footer>
</body>
</html>
"""


def related_articles(art, arts, limit=4):
    """同じタグを多く共有する記事を優先し、足りなければ新着で補う。"""
    others = [a for a in arts if a["slug"] != art["slug"]]
    my_tags = set(art.get("tags", []))

    def score(a):
        return len(my_tags & set(a.get("tags", [])))

    others.sort(key=lambda a: (score(a), a["date"], a["id"]), reverse=True)
    return others[:limit]


def render_faq_section(faqs):
    if not faqs:
        return ""
    items = "".join(
        f"<details class='faq-item'><summary>{html.escape(f['q'])}</summary>"
        f"<p>{html.escape(f['a'])}</p></details>"
        for f in faqs
    )
    return f"<section class='faq'><h2>よくある質問</h2>{items}</section>"


def render_related_section(related):
    if not related:
        return ""
    links = "".join(
        f"<li><a href='{a['slug']}.html'>{html.escape(a['title'])}</a></li>"
        for a in related
    )
    return f"<nav class='related'><h2>あわせて読みたい</h2><ul>{links}</ul></nav>"


def article_structured_data(config, art, url):
    """記事ページに埋め込む構造化データ(Article/HowTo/FAQ)をまとめて返す。"""
    site = config["site_title"]
    blocks = [jsonld({
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": art["title"],
        "description": art["description"],
        "datePublished": art["date"],
        "dateModified": art["date"],
        "author": {"@type": "Organization", "name": config.get("author", site)},
        "publisher": {"@type": "Organization", "name": site},
        "mainEntityOfPage": url,
        "inLanguage": "ja",
    })]
    steps = art.get("steps") or []
    if steps:
        blocks.append(jsonld({
            "@context": "https://schema.org",
            "@type": "HowTo",
            "name": art["title"],
            "description": art["description"],
            "step": [
                {"@type": "HowToStep", "position": i + 1,
                 "name": s["name"], "text": s["text"]}
                for i, s in enumerate(steps)
            ],
        }))
    faqs = art.get("faqs") or []
    if faqs:
        blocks.append(jsonld({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": f["q"],
                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                for f in faqs
            ],
        }))
    return "".join(blocks)


def render_article_page(config, art, arts):
    url = f"{config['site_url']}/{art['slug']}.html"
    tags = "".join(f'<span class="tag">{html.escape(t)}</span>' for t in art["tags"])
    faq_html = render_faq_section(art.get("faqs"))
    related_html = render_related_section(related_articles(art, arts))
    inner = f"""
<article>
  <p class="crumb"><a href="articles.html">詐欺対策・見守りガイド</a> ＞ 記事</p>
  <h1>{html.escape(art['title'])}</h1>
  <p class="meta">公開日: {art['date']}</p>
  <div class="tags">{tags}</div>
  <div class="article-body">
  {art['body_html']}
  </div>
  {faq_html}
  {related_html}
  <p class="back"><a href="articles.html">← ガイド一覧へ戻る</a></p>
</article>
"""
    head_extra = article_structured_data(config, art, url)
    return page_shell(config, art["title"], art["description"], inner, url, head_extra)


def render_articles_index(config, arts):
    items = ""
    for a in sorted(arts, key=lambda x: (x["date"], x["id"]), reverse=True):
        items += f"""
  <li class="card">
    <a href="{a['slug']}.html">
      <span class="card-title">{html.escape(a['title'])}</span>
      <span class="card-desc">{html.escape(a['description'])}</span>
      <span class="card-date">{a['date']}</span>
    </a>
  </li>"""
    inner = f"""
<h1 class="index-h1">詐欺対策・見守りガイド</h1>
<p class="index-lead">離れて暮らす高齢の家族の見守りと、特殊詐欺への備えに役立つ解説記事です。毎晩少しずつ増えていきます。</p>
<ul class="card-list">{items}
</ul>
<p class="count">現在 {len(arts)} 記事を公開中（毎晩自動更新）</p>
"""
    return page_shell(config, f"詐欺対策・見守りガイド | {config['site_title']}",
                      "高齢者の見守りと特殊詐欺対策について解説する記事の一覧です。",
                      inner, config["site_url"] + "/articles.html")


def service_structured_data(config, svc, url):
    return jsonld({
        "@context": "https://schema.org",
        "@type": "Service",
        "serviceType": svc.get("type", ""),
        "name": svc["name"],
        "provider": {"@type": "Organization", "name": svc.get("provider", "")},
        "description": svc.get("features", ""),
        "url": url,
    })


def render_service_card(svc):
    types = f'<span class="tag">{html.escape(svc.get("type", ""))}</span>' if svc.get("type") else ""
    fee = svc.get("monthly_fee", "") or "要問い合わせ"
    return f"""
  <li class="card">
    <a href="{svc['slug']}.html">
      <span class="card-title">{html.escape(svc['name'])}</span>
      <span class="card-desc">{html.escape(svc.get('provider', ''))} ／ 月額目安: {html.escape(fee)}</span>
      <span class="card-date">更新日: {svc.get('updated', '')}</span>
    </a>
  </li>"""


def render_services_index(config, svcs):
    items = "".join(render_service_card(s) for s in sorted(svcs, key=lambda x: x["id"]))
    inner = f"""
<h1 class="index-h1">見守りサービスを比較</h1>
<p class="index-lead">高齢の家族を見守るサービスの比較一覧です。料金・仕様は変更される場合があるため、契約前に必ず公式サイトでご確認ください。</p>
<ul class="card-list">{items}
</ul>
<p class="count">現在 {len(svcs)} 件のサービスを掲載中</p>
"""
    return page_shell(config, f"見守りサービスを比較 | {config['site_title']}",
                      "高齢者向け見守りサービスの比較ページです。",
                      inner, config["site_url"] + "/services.html")


def render_service_page(config, svc):
    url = f"{config['site_url']}/{svc['slug']}.html"
    types = f'<span class="tag">{html.escape(svc.get("type", ""))}</span>' if svc.get("type") else ""
    website_row = (
        f"<tr><th>公式サイト</th><td><a href=\"{html.escape(svc['website'])}\">{html.escape(svc['website'])}</a></td></tr>"
        if svc.get("website") else ""
    )
    inner = f"""
<article>
  <p class="crumb"><a href="services.html">見守りサービスを比較</a> ＞ 詳細</p>
  <h1>{html.escape(svc['name'])}</h1>
  <div class="tags">{types}</div>
  <table class="fac-table">
    <tr><th>提供会社</th><td>{html.escape(svc.get('provider', ''))}</td></tr>
    <tr><th>月額目安</th><td>{html.escape(svc.get('monthly_fee', ''))}</td></tr>
    <tr><th>初期費用目安</th><td>{html.escape(svc.get('initial_fee', ''))}</td></tr>
    <tr><th>こんな人向け</th><td>{html.escape(svc.get('target', ''))}</td></tr>
    {website_row}
  </table>
  <div class="article-body">
    <h2>サービスの特徴</h2>
    <p>{html.escape(svc.get('features', ''))}</p>
  </div>
  <p class="meta">情報更新日: {svc.get('updated', '')}(料金・仕様は変更される場合があります。契約前に公式サイトでご確認ください)</p>
  <p class="back"><a href="services.html">← 見守りサービス一覧へ戻る</a></p>
</article>
"""
    head_extra = service_structured_data(config, svc, url)
    return page_shell(config, f"{svc['name']} | {config['site_title']}",
                      svc.get("features", svc["name"]), inner, url, head_extra)


def municipal_structured_data(config, m, url):
    return jsonld({
        "@context": "https://schema.org",
        "@type": "GovernmentService",
        "name": m["program_name"],
        "serviceOperator": {"@type": "GovernmentOrganization", "name": m.get("area", "")},
        "description": m.get("services", ""),
        "url": url,
    })


def render_municipal_card(m):
    return f"""
  <li class="card">
    <a href="{m['slug']}.html">
      <span class="card-title">{html.escape(m['area'])} ／ {html.escape(m['program_name'])}</span>
      <span class="card-desc">費用: {html.escape(m.get('cost', ''))}</span>
      <span class="card-date">更新日: {m.get('updated', '')}</span>
    </a>
  </li>"""


def render_municipalities_index(config, munis):
    items = "".join(render_municipal_card(m) for m in sorted(munis, key=lambda x: x["id"]))
    inner = f"""
<h1 class="index-h1">自治体の無料見守り制度を比較</h1>
<p class="index-lead">お住まいの自治体によって、緊急通報装置の貸与や電話での安否確認など、無料〜低額で使える見守り制度の内容・費用は異なります。ここでは確認できた範囲の制度を紹介します。制度は変更されることがあるため、必ずお住まいの自治体窓口でも最新情報をご確認ください。</p>
<ul class="card-list">{items}
</ul>
<p class="count">現在 {len(munis)} 自治体分を掲載中(全国網羅ではありません。今後追加予定です)</p>
"""
    return page_shell(config, f"自治体の無料見守り制度を比較 | {config['site_title']}",
                      "自治体が実施している高齢者向け見守り制度の比較ページです。",
                      inner, config["site_url"] + "/municipalities.html")


def render_municipal_page(config, m):
    url = f"{config['site_url']}/{m['slug']}.html"
    caution_html = (
        f'<p class="meta">⚠ {html.escape(m["caution"])}</p>' if m.get("caution") else ""
    )
    inner = f"""
<article>
  <p class="crumb"><a href="municipalities.html">自治体の無料見守り制度を比較</a> ＞ 詳細</p>
  <h1>{html.escape(m['area'])} ／ {html.escape(m['program_name'])}</h1>
  <table class="fac-table">
    <tr><th>対象者</th><td>{html.escape(m.get('target', ''))}</td></tr>
    <tr><th>費用</th><td>{html.escape(m.get('cost', ''))}</td></tr>
    <tr><th>申込窓口</th><td>{html.escape(m.get('contact', ''))}</td></tr>
    <tr><th>情報源</th><td><a href="{html.escape(m.get('source_url', ''))}">{html.escape(m.get('source_url', ''))}</a></td></tr>
  </table>
  <div class="article-body">
    <h2>サービス内容</h2>
    <p>{html.escape(m.get('services', ''))}</p>
  </div>
  {caution_html}
  <p class="meta">情報更新日: {m.get('updated', '')}(制度は変更される場合があります。お住まいの自治体窓口でも必ずご確認ください)</p>
  <p class="back"><a href="municipalities.html">← 自治体一覧へ戻る</a></p>
</article>
"""
    head_extra = municipal_structured_data(config, m, url)
    return page_shell(config, f"{m['area']} {m['program_name']} | {config['site_title']}",
                      m.get("services", m["program_name"]), inner, url, head_extra)


def render_index(config, arts, svcs, munis):
    svc_items = "".join(render_service_card(s) for s in sorted(svcs, key=lambda x: x["id"])[:6])
    muni_items = "".join(render_municipal_card(m) for m in sorted(munis, key=lambda x: x["id"])[:6])
    art_items = ""
    for a in sorted(arts, key=lambda x: (x["date"], x["id"]), reverse=True)[:6]:
        art_items += f"""
  <li class="card">
    <a href="{a['slug']}.html">
      <span class="card-title">{html.escape(a['title'])}</span>
      <span class="card-desc">{html.escape(a['description'])}</span>
    </a>
  </li>"""
    inner = f"""
<h1 class="index-h1">{html.escape(config['site_title'])}</h1>
<p class="index-lead">{html.escape(config['site_description'])}</p>

<section>
  <h2 class="section-h2">見守りサービスを比較（{len(svcs)}件掲載中）</h2>
  <ul class="card-list">{svc_items}
  </ul>
  <p class="more"><a href="services.html">サービス一覧をすべて見る →</a></p>
</section>

<section>
  <h2 class="section-h2">自治体の無料見守り制度（{len(munis)}自治体分掲載中）</h2>
  <ul class="card-list">{muni_items}
  </ul>
  <p class="more"><a href="municipalities.html">自治体一覧をすべて見る →</a></p>
</section>

<section>
  <h2 class="section-h2">詐欺対策・見守りガイド</h2>
  <ul class="card-list">{art_items}
  </ul>
  <p class="more"><a href="articles.html">記事をすべて見る →</a></p>
</section>
"""
    head_extra = jsonld({
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": config["site_title"],
        "description": config["site_description"],
        "url": config["site_url"] + "/",
        "inLanguage": "ja",
    })
    return page_shell(config, config["site_title"], config["site_description"],
                      inner, config["site_url"] + "/", head_extra)


def render_about(config):
    inner = f"""
<article>
  <h1>運営者情報</h1>
  <div class="article-body">
    <h2>運営方針</h2>
    <p>{html.escape(config.get('operator_note', ''))}</p>
    <h2>免責事項</h2>
    <p>{html.escape(config.get('disclaimer', ''))}</p>
    <h2>お問い合わせ</h2>
    <p>お問い合わせ先は準備中です。決まり次第こちらに掲載します。</p>
  </div>
  <p class="back"><a href="index.html">← トップへ戻る</a></p>
</article>
"""
    return page_shell(config, f"運営者情報 | {config['site_title']}",
                      "本サイトの運営方針・免責事項についてのページです。",
                      inner, config["site_url"] + "/about.html")


def render_sitemap(config, arts, svcs, munis):
    urls = [
        f"  <url><loc>{config['site_url']}/</loc></url>",
        f"  <url><loc>{config['site_url']}/services.html</loc></url>",
        f"  <url><loc>{config['site_url']}/municipalities.html</loc></url>",
        f"  <url><loc>{config['site_url']}/articles.html</loc></url>",
        f"  <url><loc>{config['site_url']}/about.html</loc></url>",
    ]
    for a in arts:
        urls.append(
            f"  <url><loc>{config['site_url']}/{a['slug']}.html</loc>"
            f"<lastmod>{a['date']}</lastmod></url>"
        )
    for s in svcs:
        urls.append(
            f"  <url><loc>{config['site_url']}/{s['slug']}.html</loc>"
            f"<lastmod>{s.get('updated', '')}</lastmod></url>"
        )
    for m in munis:
        urls.append(
            f"  <url><loc>{config['site_url']}/{m['slug']}.html</loc>"
            f"<lastmod>{m.get('updated', '')}</lastmod></url>"
        )
    body = "\n".join(urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{body}\n</urlset>\n")


STYLE = """:root{--bg:#f6f8fa;--ink:#2b2b2b;--accent:#2d7dc4;--card:#fff;--line:#e2e8ee}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,"Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif;
background:var(--bg);color:var(--ink);line-height:1.8}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.site-header{background:#fff;border-bottom:1px solid var(--line);padding:18px 20px;text-align:center}
.site-title{font-size:1.3rem;font-weight:700;color:var(--ink)}
.site-tagline{margin:6px 0 0;font-size:.8rem;color:#777}
.site-nav{margin-top:12px;display:flex;gap:16px;justify-content:center;flex-wrap:wrap;font-size:.85rem}
.container{max-width:760px;margin:0 auto;padding:24px 18px}
.index-h1{font-size:1.5rem}.index-lead{color:#555}
.section-h2{font-size:1.15rem;border-left:5px solid var(--accent);padding-left:12px;margin-top:34px}
.card-list{list-style:none;padding:0;margin:0;display:grid;gap:14px}
.card a{display:block;background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:16px 18px;color:var(--ink)}
.card a:hover{border-color:var(--accent);text-decoration:none}
.card-title{display:block;font-weight:700;font-size:1.05rem}
.card-desc{display:block;color:#666;font-size:.85rem;margin:6px 0}
.card-date{display:block;color:#aaa;font-size:.75rem}
.more{margin-top:10px;font-size:.85rem}
.count{color:#999;font-size:.8rem;text-align:center;margin-top:16px}
article h1{font-size:1.5rem;line-height:1.4}
.crumb{font-size:.8rem;color:#999}.meta{color:#999;font-size:.8rem}
.tags{margin:8px 0 20px}.tag{display:inline-block;background:#e7f0f8;color:#2d5f8a;
font-size:.72rem;padding:3px 8px;border-radius:20px;margin-right:6px}
.fac-table{width:100%;border-collapse:collapse;margin:16px 0}
.fac-table th{text-align:left;color:#666;font-size:.85rem;padding:8px 12px 8px 0;width:110px;vertical-align:top}
.fac-table td{padding:8px 0;border-bottom:1px solid var(--line)}
.article-body h2{border-left:5px solid var(--accent);padding-left:12px;margin-top:34px;font-size:1.2rem}
.article-body h3{margin-top:24px;font-size:1.05rem}
.article-body ul,.article-body ol{padding-left:1.4em}
.back{margin-top:40px}
.faq{margin-top:40px}.faq h2{border-left:5px solid var(--accent);padding-left:12px;font-size:1.2rem}
.faq-item{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:10px 0}
.faq-item summary{font-weight:700;cursor:pointer}
.faq-item p{margin:10px 0 0;color:#555}
.related{margin-top:40px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 20px}
.related h2{font-size:1.1rem;margin-top:0}
.related ul{margin:0;padding-left:1.2em}.related li{margin:6px 0}
.site-footer{border-top:1px solid var(--line);padding:24px 18px;text-align:center;color:#999;font-size:.78rem}
.disclaimer{max-width:600px;margin:0 auto 10px}
"""


def build_site(config):
    arts = [load_json(p, None) for p in sorted(ARTICLES.glob("post-*.json"))]
    arts = [a for a in arts if a]

    all_svcs = load_json(DATA / "services.json", [])
    svcs = [s for s in all_svcs if s.get("status") == "published"]

    all_munis = load_json(DATA / "municipalities.json", [])
    munis = [m for m in all_munis if m.get("status") == "published"]

    DOCS.mkdir(exist_ok=True)
    (DOCS / "style.css").write_text(STYLE, encoding="utf-8")
    (DOCS / "index.html").write_text(render_index(config, arts, svcs, munis), encoding="utf-8")
    (DOCS / "articles.html").write_text(render_articles_index(config, arts), encoding="utf-8")
    (DOCS / "services.html").write_text(render_services_index(config, svcs), encoding="utf-8")
    (DOCS / "municipalities.html").write_text(render_municipalities_index(config, munis), encoding="utf-8")
    (DOCS / "about.html").write_text(render_about(config), encoding="utf-8")
    (DOCS / "sitemap.xml").write_text(render_sitemap(config, arts, svcs, munis), encoding="utf-8")
    (DOCS / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {config['site_url']}/sitemap.xml\n",
        encoding="utf-8")
    for a in arts:
        (DOCS / f"{a['slug']}.html").write_text(
            render_article_page(config, a, arts), encoding="utf-8")
    for s in svcs:
        (DOCS / f"{s['slug']}.html").write_text(
            render_service_page(config, s), encoding="utf-8")
    for m in munis:
        (DOCS / f"{m['slug']}.html").write_text(
            render_municipal_page(config, m), encoding="utf-8")
    print(f"[build] サイトを生成: 記事{len(arts)}件 / サービス{len(svcs)}件 / 自治体{len(munis)}件")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="API無しでサンプル記事を作る")
    parser.add_argument("--build-only", action="store_true", help="サイトだけ作り直す")
    args = parser.parse_args()

    config = load_json(DATA / "config.json", {})
    ARTICLES.mkdir(parents=True, exist_ok=True)  # 空だとGitに無い場合があるので必ず用意
    if args.build_only:
        build_site(config)
        return

    keywords = load_json(DATA / "keywords.json", [])
    todo = [k for k in keywords if k.get("status") == "todo"]
    n = 1 if args.demo else config.get("articles_per_run", 3)
    targets = todo[:n]

    if not targets:
        print("[info] 未執筆のキーワードがありません。data/keywords.json に追加してください。")
        build_site(config)
        return

    for kw in targets:
        print(f"[write] 執筆中: {kw['query']}")
        try:
            content = demo_article(kw["query"]) if args.demo \
                else generate_with_claude(kw["query"], config.get("model", "claude-sonnet-4-6"))
        except Exception as e:  # noqa: BLE001
            print(f"[error] 失敗: {kw['query']} -> {e}", file=sys.stderr)
            continue
        record = build_article_record(kw, content)
        write_json(ARTICLES / f"{record['slug']}.json", record)
        kw["status"] = "done"
        print(f"[ok] 完成: {record['title']}")

    write_json(DATA / "keywords.json", keywords)
    build_site(config)
    print("[done] 完了。")


if __name__ == "__main__":
    main()

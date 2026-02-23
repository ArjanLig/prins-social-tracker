# ai_insights.py
"""AI-analyse module voor Prins Social Tracker — GPT-4o-mini."""

import os
from datetime import datetime, timezone

import streamlit as st
from openai import OpenAI


DAGEN_NL = {
    "Monday": "Maandag", "Tuesday": "Dinsdag", "Wednesday": "Woensdag",
    "Thursday": "Donderdag", "Friday": "Vrijdag", "Saturday": "Zaterdag",
    "Sunday": "Zondag",
}


def _get_secret(key: str, default: str = "") -> str:
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return os.getenv(key, default)


def _call_openai(system_prompt: str, user_prompt: str) -> str:
    """Stuur een prompt naar OpenAI GPT-4o-mini en return het antwoord."""
    api_key = _get_secret("OPENAI_API_KEY")
    if not api_key:
        return "⚠️ Geen OPENAI_API_KEY gevonden. Voeg deze toe in Streamlit Cloud → Settings → Secrets."

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=1500,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ OpenAI fout: {e}"


MAAND_NL = {
    "01": "Januari", "02": "Februari", "03": "Maart", "04": "April",
    "05": "Mei", "06": "Juni", "07": "Juli", "08": "Augustus",
    "09": "September", "10": "Oktober", "11": "November", "12": "December",
}


def _build_posts_summary(posts: list[dict], platform: str, page: str,
                         follower_count: int | None = None) -> str:
    """Bouw een uitgebreide data-samenvatting van posts voor de AI."""
    if not posts:
        return "Geen posts beschikbaar."

    lines = [f"Platform: {platform.capitalize()}", f"Merk: {page.capitalize()}"]
    if follower_count:
        lines.append(f"Huidige volgers: {follower_count:,}")
    lines.append(f"Totaal posts in database: {len(posts)}")

    # ── Totalen ──
    total_likes = sum(p.get("likes", 0) or 0 for p in posts)
    total_comments = sum(p.get("comments", 0) or 0 for p in posts)
    total_shares = sum(p.get("shares", 0) or 0 for p in posts)
    total_reach = sum(p.get("reach", 0) or 0 for p in posts)
    total_views = sum(p.get("impressions", 0) or 0 for p in posts)
    lines.append(f"Totaal: {total_likes} likes, {total_comments} reacties, "
                 f"{total_shares} shares, bereik {total_reach:,}, weergaven {total_views:,}")

    # ── Maandelijks overzicht ──
    monthly: dict[str, list[dict]] = {}
    for p in posts:
        month_key = (p.get("date") or "")[:7]
        if month_key:
            monthly.setdefault(month_key, []).append(p)

    if monthly:
        lines.append("\n## Maandelijks overzicht")
        lines.append("Maand | Posts | Likes | Reacties | Shares | Bereik | Weergaven | Gem.ER%")
        lines.append("--- | --- | --- | --- | --- | --- | --- | ---")
        for month_key in sorted(monthly.keys(), reverse=True):
            mp = monthly[month_key]
            m_likes = sum(p.get("likes", 0) or 0 for p in mp)
            m_comments = sum(p.get("comments", 0) or 0 for p in mp)
            m_shares = sum(p.get("shares", 0) or 0 for p in mp)
            m_reach = sum(p.get("reach", 0) or 0 for p in mp)
            m_views = sum(p.get("impressions", 0) or 0 for p in mp)
            m_er = sum(p.get("engagement_rate", 0) or 0 for p in mp) / len(mp) if mp else 0
            mm = month_key[5:7]
            label = f"{MAAND_NL.get(mm, mm)} {month_key[:4]}"
            lines.append(f"{label} | {len(mp)} | {m_likes} | {m_comments} | "
                         f"{m_shares} | {m_reach:,} | {m_views:,} | {m_er:.2f}%")

    # ── Alle posts (compact) ──
    lines.append("\n## Alle posts (gesorteerd op datum, nieuwste eerst)")
    lines.append("Datum | Type | Likes | Reacties | Shares | Bereik | Weergaven | Tekst")
    lines.append("--- | --- | --- | --- | --- | --- | --- | ---")
    sorted_by_date = sorted(posts, key=lambda p: p.get("date", ""), reverse=True)
    for p in sorted_by_date:
        date = (p.get("date") or "")[:10]
        ptype = p.get("type", "Post")
        likes = p.get("likes", 0) or 0
        comments = p.get("comments", 0) or 0
        shares = p.get("shares", 0) or 0
        reach = p.get("reach", 0) or 0
        views = p.get("impressions", 0) or 0
        text = (p.get("text") or "")[:80].replace("\n", " ").replace("|", "/")
        lines.append(f"{date} | {ptype} | {likes} | {comments} | {shares} | "
                     f"{reach} | {views} | {text}")

    # ── Top & flop posts ──
    sorted_engagement = sorted(posts,
                               key=lambda p: (p.get("likes", 0) or 0) + (p.get("comments", 0) or 0),
                               reverse=True)
    lines.append("\n## Top 5 posts (hoogste engagement)")
    for i, p in enumerate(sorted_engagement[:5], 1):
        text = (p.get("text") or "(geen tekst)")[:100].replace("\n", " ")
        date = (p.get("date") or "")[:10]
        likes = p.get("likes", 0) or 0
        comments = p.get("comments", 0) or 0
        reach = p.get("reach", 0) or 0
        ptype = p.get("type", "Post")
        lines.append(f"  {i}. ({date}, {ptype}) {likes} likes, {comments} reacties, "
                     f"bereik {reach} — \"{text}\"")

    if len(sorted_engagement) > 5:
        lines.append("\n## Minst presterende 5 posts")
        for i, p in enumerate(sorted_engagement[-5:], 1):
            text = (p.get("text") or "(geen tekst)")[:100].replace("\n", " ")
            date = (p.get("date") or "")[:10]
            likes = p.get("likes", 0) or 0
            comments = p.get("comments", 0) or 0
            reach = p.get("reach", 0) or 0
            lines.append(f"  {i}. ({date}) {likes} likes, {comments} reacties, "
                         f"bereik {reach} — \"{text}\"")

    # ── Posting patronen ──
    dag_counts: dict[str, int] = {}
    uur_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for p in posts:
        date_str = p.get("date", "")
        if not date_str:
            continue
        try:
            dt = datetime.fromisoformat(date_str.replace("+0000", "+00:00"))
            dag = DAGEN_NL.get(dt.strftime("%A"), dt.strftime("%A"))
            dag_counts[dag] = dag_counts.get(dag, 0) + 1
            uur = f"{dt.hour:02d}:00"
            uur_counts[uur] = uur_counts.get(uur, 0) + 1
        except (ValueError, TypeError):
            pass
        ptype = p.get("type", "Post")
        type_counts[ptype] = type_counts.get(ptype, 0) + 1

    if dag_counts or uur_counts or type_counts:
        lines.append("\n## Posting patronen")
        if dag_counts:
            lines.append(f"Dagen: {dag_counts}")
        if uur_counts:
            lines.append(f"Uren: {dict(sorted(uur_counts.items()))}")
        if type_counts:
            lines.append(f"Content types: {type_counts}")

    return "\n".join(lines)


def analyze_posts(posts: list[dict], platform: str, page: str,
                  follower_count: int | None = None) -> str:
    """Analyseer posts van een specifiek platform/merk met AI."""
    summary = _build_posts_summary(posts, platform, page, follower_count)

    system_prompt = (
        "Je bent een ervaren social media analist die werkt voor Prins Petfoods, "
        "een Nederlands premium diervoedingsbedrijf. Analyseer de data en geef je "
        "analyse in het Nederlands met deze structuur:\n\n"
        "1. **Samenvatting** — kort overzicht van de belangrijkste cijfers\n"
        "2. **Sterke punten** — wat gaat goed, welke content scoort\n"
        "3. **Verbeterpunten** — waar liggen kansen\n"
        "4. **Trends** — opvallende patronen in timing, type content, engagement\n"
        "5. **Concrete aanbevelingen** — 3-5 specifieke acties\n\n"
        "Wees specifiek en actionable. Verwijs naar concrete posts of cijfers. "
        "Houd rekening met de doelgroep: huisdiereigenaren in Nederland/België."
    )

    return _call_openai(system_prompt, f"Analyseer deze social media data:\n\n{summary}")


def generate_monthly_report(posts: list[dict], platform: str, page: str,
                            month: str, follower_count: int | None = None) -> str:
    """Genereer een maandrapport voor een specifiek platform/merk."""
    # Filter posts voor de opgegeven maand
    month_posts = [p for p in posts if (p.get("date") or "")[:7] == month]

    if not month_posts:
        return f"Geen posts gevonden voor {month}."

    summary = _build_posts_summary(month_posts, platform, page, follower_count)

    system_prompt = (
        "Je bent een social media manager bij Prins Petfoods, een Nederlands premium "
        "diervoedingsbedrijf. Schrijf een professioneel maandrapport in het Nederlands "
        "met deze structuur:\n\n"
        "## Maandrapport {platform} — {maand}\n\n"
        "1. **Overzicht** — kernresultaten van de maand in cijfers\n"
        "2. **Highlights** — best presterende content en waarom\n"
        "3. **Aandachtspunten** — wat kan beter\n"
        "4. **Vergelijking** — hoe verhoudt deze maand zich (op basis van beschikbare data)\n"
        "5. **Actiepunten volgende maand** — 3 concrete verbeterpunten\n\n"
        "Schrijf helder en bondig. Gebruik cijfers uit de data."
    )

    return _call_openai(system_prompt,
                        f"Schrijf een maandrapport voor {month}:\n\n{summary}")


def suggest_content(posts: list[dict], platform: str, page: str,
                    follower_count: int | None = None) -> str:
    """Genereer content-suggesties op basis van historische prestaties."""
    summary = _build_posts_summary(posts, platform, page, follower_count)

    system_prompt = (
        "Je bent een creatieve social media strateeg bij Prins Petfoods, een Nederlands "
        "premium diervoedingsbedrijf (honden- en kattenvoeding). Op basis van de prestaties "
        "van eerdere posts, geef je concrete content-suggesties in het Nederlands.\n\n"
        "Structuur:\n"
        "1. **Best werkende content-types** — welk format scoort het beste\n"
        "2. **Optimale timing** — wanneer posten voor maximaal bereik\n"
        "3. **Onderwerpen die scoren** — thema's die resoneren bij de doelgroep\n"
        "4. **5 concrete post-ideeën** — inclusief format, timing en caption-suggestie\n"
        "5. **Wat te vermijden** — welk type content minder goed werkt\n\n"
        "Wees creatief maar realistisch. Focus op de huisdierensector."
    )

    return _call_openai(system_prompt,
                        f"Geef content-suggesties op basis van deze data:\n\n{summary}")


def build_cross_platform_summary(all_posts: dict[str, list[dict]],
                                 follower_counts: dict[str, int | None]) -> str:
    """Bouw een samenvatting over alle platformen/merken heen.

    all_posts: {"{page}_{platform}": [posts...]}
    follower_counts: {"{page}_{platform}": count}
    """
    sections = []
    for key in sorted(all_posts.keys()):
        posts = all_posts[key]
        if not posts:
            continue
        page, platform = key.rsplit("_", 1)
        fc = follower_counts.get(key)
        sections.append(_build_posts_summary(posts, platform, page, fc))

    return "\n\n" + ("=" * 60 + "\n\n").join(sections)


def generate_cross_platform_report(all_posts: dict[str, list[dict]],
                                   follower_counts: dict[str, int | None],
                                   month: str) -> str:
    """Genereer een maandrapport over alle platformen en merken heen."""
    summary = build_cross_platform_summary(all_posts, follower_counts)

    system_prompt = (
        "Je bent de social media manager van Prins Petfoods, een Nederlands premium "
        "diervoedingsbedrijf. Je beheert meerdere merken (Prins, Edupet) op meerdere "
        "platformen (Instagram, Facebook, TikTok). Schrijf een overkoepelend maandrapport "
        "in het Nederlands.\n\n"
        "Structuur:\n"
        "## Maandrapport Social Media — {maand}\n\n"
        "1. **Overzicht per kanaal** — tabel met kernresultaten per merk/platform\n"
        "2. **Highlights** — best presterende content over alle kanalen\n"
        "3. **Cross-platform inzichten** — vergelijking tussen platformen/merken\n"
        "4. **Trends** — wat valt op deze maand\n"
        "5. **Actiepunten** — 3-5 concrete verbeterpunten voor volgende maand\n\n"
        "Vergelijk de prestaties tussen merken en platformen. Wees specifiek met cijfers."
    )

    return _call_openai(system_prompt,
                        f"Schrijf een overkoepelend maandrapport voor {month}:\n\n{summary}")


def analyze_cross_platform(all_posts: dict[str, list[dict]],
                           follower_counts: dict[str, int | None]) -> str:
    """Cross-platform analyse over alle merken."""
    summary = build_cross_platform_summary(all_posts, follower_counts)

    system_prompt = (
        "Je bent een ervaren social media analist bij Prins Petfoods, een Nederlands "
        "premium diervoedingsbedrijf. Je analyseert de prestaties over alle merken en "
        "platformen heen. Geef je analyse in het Nederlands:\n\n"
        "1. **Overzicht** — samenvatting per merk/platform\n"
        "2. **Vergelijking** — welke kanalen presteren het best en waarom\n"
        "3. **Sterke punten** — wat werkt goed, cross-platform patronen\n"
        "4. **Kansen** — waar liggen groeimogelijkheden\n"
        "5. **Aanbevelingen** — 5 specifieke acties met prioriteit\n\n"
        "Wees specifiek. Vergelijk merken en platformen met cijfers."
    )

    return _call_openai(system_prompt,
                        f"Analyseer alle social media data:\n\n{summary}")


def suggest_content_cross_platform(all_posts: dict[str, list[dict]],
                                   follower_counts: dict[str, int | None]) -> str:
    """Cross-platform content suggesties."""
    summary = build_cross_platform_summary(all_posts, follower_counts)

    system_prompt = (
        "Je bent een creatieve social media strateeg bij Prins Petfoods, een Nederlands "
        "premium diervoedingsbedrijf (honden- en kattenvoeding). Op basis van prestaties "
        "over alle platformen en merken, geef je content-suggesties in het Nederlands.\n\n"
        "Structuur:\n"
        "1. **Per platform** — wat werkt het best op elk platform\n"
        "2. **Cross-platform strategie** — hoe content hergebruiken tussen kanalen\n"
        "3. **Optimale timing per platform** — wanneer posten\n"
        "4. **10 concrete post-ideeën** — per platform, met format en caption-suggestie\n"
        "5. **Merkstrategie** — hoe Prins vs Edupet zich moeten onderscheiden\n\n"
        "Wees creatief maar realistisch. Focus op de huisdierensector."
    )

    return _call_openai(system_prompt,
                        f"Geef content-suggesties op basis van alle data:\n\n{summary}")


def chat_with_data(data_summary: str, messages: list[dict]) -> str:
    """Vrije chat over de social media data. Houdt conversatiegeschiedenis bij."""
    api_key = _get_secret("OPENAI_API_KEY")
    if not api_key:
        return "Geen OPENAI_API_KEY gevonden — chat niet beschikbaar."

    system_prompt = (
        "Je bent een behulpzame social media analist bij Prins Petfoods, een Nederlands "
        "premium diervoedingsbedrijf. Je beantwoordt vragen over de social media data "
        "in het Nederlands. Je hebt toegang tot de volgende data:\n\n"
        f"{data_summary}\n\n"
        "Antwoord altijd in het Nederlands. Wees specifiek en verwijs naar cijfers "
        "uit de data wanneer relevant. Als je iets niet kunt afleiden uit de data, "
        "zeg dat eerlijk."
    )

    api_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        api_messages.append({"role": msg["role"], "content": msg["content"]})

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=api_messages,
        temperature=0.7,
        max_tokens=1500,
    )
    return response.choices[0].message.content

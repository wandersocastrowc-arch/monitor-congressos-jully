#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agregador do Monitor de Congressos & Publicacoes da Jully.

A cada execucao (seg/qua 7h via GitHub Actions):
  1. Carrega events.json e sources.json
  2. Recalcula status por prazo (abre/encerra sozinho)
  3. Coleta candidatos de MULTIPLAS fontes:
       - Feeds RSS/Atom (associacoes + revistas OJS)         [sem chave]
       - DOAJ  (revistas de acesso aberto por assunto)        [sem chave]
       - OpenAlex (fontes/venues por assunto)                 [sem chave]
       - WikiCFP (chamadas por categoria)                     [sem chave]
       - Google Custom Search (busca ampla na web)            [opcional: GOOGLE_API_KEY + GOOGLE_CSE_ID]
  4. Curadoria: por IA se ANTHROPIC_API_KEY existir; senao, filtro por palavras-chave
  5. Faz merge/dedupe por id e link, com teto de novos itens
  6. Salva events.json e last_update.json
  7. Envia e-mail digest (se GMAIL_USER/GMAIL_APP_PASSWORD/MAIL_TO existirem)

Tudo e resiliente: qualquer fonte/camada que falhar e ignorada; o resto continua.
"""

import json, os, re, datetime, unicodedata, smtplib, ssl, urllib.request, urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

ROOT = os.path.dirname(os.path.abspath(__file__))
EVENTS = os.path.join(ROOT, "events.json")
SOURCES = os.path.join(ROOT, "sources.json")
LAST = os.path.join(ROOT, "last_update.json")
TODAY = datetime.date.today()
UA = "Mozilla/5.0 (compatible; MonitorCongressos/1.0; +https://github.com)"
MAX_NEW = 30          # teto de itens novos por rodada
MAX_DOAJ = 8          # teto de revistas novas por consulta DOAJ

KEYWORDS = [
    "metadat", "flusser", "information science", "ciencia da informacao",
    "knowledge organization", "organizacion del conocimiento",
    "organizacao do conhecimento", "digital humanities", "humanidades digit",
    "dublin core", "linked data", "ontolog", "semantic web", "thesaur", "vocabular",
    "scholarly communication", "comunicacao", "comunicacion", "media studies",
    "cultural heritage", "patrimonio", "archive", "archiv", "librar", "biblioteca",
    "data curation", "preservation", "preservacao", "imagem", "visual culture",
    "documentation", "documentacion", "documentacao", "chamada", "convocatoria",
    "call for papers", "dossie", "dossier",
]
BLOCK = ["bioinformat", "medical imaging", "biostatist", "wireless", "robot",
         "vlsi", "antenna", "petroleum", "agricultur", "nanomaterial", "oncolog"]


def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:60] or "item"


def norm_link(u):
    u = (u or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"[#?].*$", "", u)
    return u.rstrip("/")


def parse_date(iso):
    try:
        return datetime.date.fromisoformat(iso)
    except Exception:
        return None


def relevant(text):
    t = (text or "").lower()
    if any(b in t for b in BLOCK):
        return False
    return any(k in t for k in KEYWORDS)


MESES = {"jan": 1, "fev": 2, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "mai": 5,
         "may": 5, "jun": 6, "jul": 7, "ago": 8, "aug": 8, "set": 9, "sep": 9,
         "out": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12, "ene": 1, "abe": 4}


def extract_deadline(text):
    if not text:
        return None
    t = text.lower()
    m = re.search(r"(\d{1,2})[/\.](\d{1,2})[/\.](\d{4})", t)         # 30/06/2026
    if m:
        try:
            return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except Exception:
            pass
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)                      # 2026-06-30
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            pass
    m = re.search(r"([a-z]{3,9})\s+(\d{1,2}),\s*(\d{4})", t)          # Aug 1, 2026
    if m and m.group(1)[:3] in MESES:
        try:
            return datetime.date(int(m.group(3)), MESES[m.group(1)[:3]], int(m.group(2)))
        except Exception:
            pass
    m = re.search(r"(\d{1,2})\s+de\s+([a-z]{3,9})\s+de\s+(\d{4})", t)  # 30 de junho de 2026
    if m and m.group(2)[:3] in MESES:
        try:
            return datetime.date(int(m.group(3)), MESES[m.group(2)[:3]], int(m.group(1)))
        except Exception:
            pass
    return None


def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def http_json(url, timeout=25):
    return json.loads(http_get(url, timeout))


# ----------------------------------------------------------------- fetchers
def fetch_rss(feeds):
    out = []
    try:
        import feedparser
    except Exception:
        print("[rss] feedparser indisponivel.")
        return out
    for f in feeds:
        url = f.get("url")
        try:
            d = feedparser.parse(url, agent=UA)
            if not d.entries:
                print("[rss] sem entradas: " + url)
                continue
        except Exception as e:
            print("[rss] falha " + url + ": " + str(e))
            continue
        for e in d.entries[:25]:
            title = (e.get("title") or "").strip()
            summary = (e.get("summary") or e.get("description") or "")[:600]
            link = (e.get("link") or "").strip()
            if not title or not link:
                continue
            out.append({"nome": title, "summary": summary, "link": link,
                        "inst": d.feed.get("title", "Fonte RSS"),
                        "areas": list(f.get("area", [])), "tipo": f.get("tipo", "Congresso"),
                        "idioma": "PT", "source": "RSS"})
        print("[rss] " + url + ": " + str(len(d.entries)) + " entradas lidas")
    return out


def fetch_wikicfp(cats):
    out = []
    try:
        import feedparser
    except Exception:
        return out
    for cat in cats:
        url = "http://www.wikicfp.com/cfp/rss?cat=" + cat
        try:
            d = feedparser.parse(url, agent=UA)
            if getattr(d, "status", 200) in (403, 429) or not d.entries:
                print("[wikicfp] " + cat + ": sem dados (status " + str(getattr(d, "status", "?")) + ")")
                continue
        except Exception as e:
            print("[wikicfp] falha " + cat + ": " + str(e))
            continue
        for e in d.entries[:40]:
            title = (e.get("title") or "").strip()
            summary = e.get("summary") or e.get("description") or ""
            link = (e.get("link") or "").strip()
            if title and link:
                out.append({"nome": title, "summary": summary, "link": link,
                            "inst": "Via WikiCFP", "areas": [cat.replace("+", " ")],
                            "tipo": "Congresso", "idioma": "EN", "source": "WikiCFP"})
    return out


def fetch_doaj(queries):
    out = []
    for q in queries:
        url = "https://doaj.org/api/v2/search/journals/" + urllib.parse.quote(q) + "?pageSize=12"
        try:
            data = http_json(url)
        except Exception as e:
            print("[doaj] falha " + q + ": " + str(e))
            continue
        added = 0
        for r in data.get("results", []):
            if added >= MAX_DOAJ:
                break
            bj = r.get("bibjson", {})
            langs = [l.upper() for l in bj.get("language", [])]
            if not (set(langs) & {"PT", "ES", "EN"}):
                continue
            title = bj.get("title", "").strip()
            jurl = (bj.get("ref", {}) or {}).get("journal", "")
            if not title or not jurl:
                continue
            apc = (bj.get("apc", {}) or {}).get("has_apc", True)
            kw = ", ".join(bj.get("keywords", [])[:5])
            idioma = "/".join([x for x in ["PT", "ES", "EN"] if x in langs]) or "EN"
            out.append({"nome": title, "summary": kw, "link": jurl,
                        "inst": (bj.get("publisher", {}) or {}).get("name", "Revista (DOAJ)"),
                        "areas": [k for k in bj.get("keywords", [])[:3]] or ["periódico"],
                        "tipo": "Periódico", "idioma": idioma, "source": "DOAJ",
                        "status": "always",
                        "obs": "Revista de acesso aberto (DOAJ)." + ("" if apc else " Sem taxa de publicacao (sem APC).")})
            added += 1
        print("[doaj] " + q + ": +" + str(added))
    return out


def fetch_openalex(queries):
    out = []
    for q in queries:
        url = "https://api.openalex.org/sources?search=" + urllib.parse.quote(q) + "&per_page=8&filter=type:journal"
        try:
            data = http_json(url)
        except Exception as e:
            print("[openalex] falha " + q + ": " + str(e))
            continue
        for s in data.get("results", [])[:5]:
            title = (s.get("display_name") or "").strip()
            link = s.get("homepage_url") or (s.get("ids", {}) or {}).get("openalex", "")
            if not title or not link:
                continue
            out.append({"nome": title, "summary": q, "link": link,
                        "inst": s.get("host_organization_name") or "Fonte (OpenAlex)",
                        "areas": [q], "tipo": "Periódico", "idioma": "multi",
                        "source": "OpenAlex", "status": "always",
                        "obs": "Venue identificada via OpenAlex - confirmar escopo e idioma."})
        print("[openalex] " + q + ": ok")
    return out


def fetch_google(queries):
    key = os.environ.get("GOOGLE_API_KEY")
    cx = os.environ.get("GOOGLE_CSE_ID")
    out = []
    if not (key and cx):
        print("[google] sem GOOGLE_API_KEY/GOOGLE_CSE_ID - pulando busca web ampla.")
        return out
    for q in queries:
        url = ("https://www.googleapis.com/customsearch/v1?key=" + key + "&cx=" + cx
               + "&num=8&q=" + urllib.parse.quote(q))
        try:
            data = http_json(url)
        except Exception as e:
            print("[google] falha: " + str(e))
            continue
        for it in data.get("items", []):
            out.append({"nome": it.get("title", "").strip(),
                        "summary": it.get("snippet", ""), "link": it.get("link", ""),
                        "inst": "Via busca web", "areas": [], "tipo": "Congresso",
                        "idioma": "multi", "source": "Google"})
    print("[google] " + str(len(out)) + " resultados")
    return out


# ----------------------------------------------------------------- curadoria
def ai_curate(cands):
    """Se ANTHROPIC_API_KEY existir, usa Claude para filtrar/enriquecer. Senao, None."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not cands:
        return None
    compact = [{"i": n, "t": c["nome"][:160], "s": (c.get("summary") or "")[:240],
                "src": c["source"]} for n, c in enumerate(cands)]
    prompt = (
        "Voce e curador de uma pesquisadora (mestrado) cujas areas sao: metadados, "
        "ciencia da informacao, organizacao do conhecimento, comunicacao, Vilem Flusser, "
        "filosofia da imagem, IA aplicada e humanidades digitais. Foco ibero-americano "
        "(PT/ES) mas aceita eventos internacionais relevantes em ingles.\n"
        "Para CADA item abaixo decida se interessa (congresso, chamada de trabalhos, "
        "periodico ou dossie aderente). Responda APENAS um JSON: uma lista de objetos "
        "{\"i\":indice,\"keep\":true/false,\"score\":0-100,\"areas\":[ate 3 tags em pt],"
        "\"resumo\":\"1 frase em pt\"}. Sem texto fora do JSON.\n\nITENS:\n"
        + json.dumps(compact, ensure_ascii=False))
    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            resp = json.loads(r.read().decode("utf-8"))
        text = "".join(b.get("text", "") for b in resp.get("content", []))
        text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
        verdicts = json.loads(text)
        by_i = {v["i"]: v for v in verdicts if isinstance(v, dict) and "i" in v}
        kept = []
        for n, c in enumerate(cands):
            v = by_i.get(n)
            if not v or not v.get("keep"):
                continue
            if v.get("score", 0) < 55:
                continue
            if v.get("areas"):
                c["areas"] = v["areas"][:3]
            if v.get("resumo"):
                c["obs"] = (v["resumo"] + " " + c.get("obs", "")).strip()
            c["score"] = v.get("score", 0)
            kept.append(c)
        kept.sort(key=lambda x: x.get("score", 0), reverse=True)
        print("[ia] curadoria: " + str(len(kept)) + " de " + str(len(cands)) + " aprovados")
        return kept
    except Exception as e:
        print("[ia] falha na curadoria: " + str(e))
        return None


# ----------------------------------------------------------------- nucleo
def recompute_status(items):
    changed = []
    for it in items:
        if it.get("status") in ("always", "monitor"):
            continue
        d = parse_date(it.get("prazoSort", ""))
        if not d:
            continue
        new = "closed" if d < TODAY else "open"
        if new != it.get("status"):
            if new == "closed":
                changed.append(it)
            it["status"] = new
    return changed


def to_item(c):
    deadline = extract_deadline((c.get("nome", "") + " " + c.get("summary", "")))
    if c.get("status") == "always":
        prazo, prazoSort, status = "Sempre aberto", "2099-01-01", "always"
    elif deadline:
        if deadline < TODAY:
            return None
        prazo, prazoSort, status = "Submissao ate " + deadline.isoformat(), deadline.isoformat(), "open"
    else:
        prazo, prazoSort, status = "Verificar prazo", "2099-01-01", "monitor"
    areas = c.get("areas") or []
    if not areas:
        areas = ["a confirmar"]
    obs = c.get("obs", "")
    if c["source"] in ("WikiCFP", "Google", "RSS"):
        obs = (obs + " Descoberto via " + c["source"] + " - confira a chamada oficial.").strip()
    return {
        "id": c["source"][:4].lower() + "-" + slug(c["nome"]),
        "nome": c["nome"], "inst": c.get("inst", ""), "tipo": c.get("tipo", "Congresso"),
        "areas": areas, "mod": "varia", "modLabel": "Verificar modalidade",
        "local": "", "idioma": c.get("idioma", "multi"), "evento": "",
        "prazo": prazo, "prazoSort": prazoSort, "status": status,
        "recorrente": False, "novo": True, "addedOn": TODAY.isoformat(),
        "fonte": c["source"], "obs": obs, "link": c["link"],
    }


def collect(cfg, existing_links, existing_ids):
    cands = []
    cands += fetch_rss(cfg.get("rss_feeds", []))
    cands += fetch_doaj(cfg.get("doaj_queries", []))
    cands += fetch_openalex(cfg.get("openalex_queries", []))
    cands += fetch_wikicfp(cfg.get("wikicfp_cats", []))
    cands += fetch_google(cfg.get("google_cse_queries", []))

    seen = set(existing_links)
    uniq = []
    for c in cands:
        nl = norm_link(c.get("link"))
        if not nl or nl in seen:
            continue
        seen.add(nl)
        uniq.append(c)
    print("[collect] " + str(len(cands)) + " candidatos, " + str(len(uniq)) + " novos (pos-dedupe por link)")

    curated = ai_curate(uniq)
    if curated is None:
        curated = [c for c in uniq if c.get("status") == "always" or relevant(c["nome"] + " " + c.get("summary", ""))]
        print("[curadoria] sem IA - filtro por palavras-chave: " + str(len(curated)))

    new_items = []
    for c in curated[:MAX_NEW]:
        it = to_item(c)
        if it and it["id"] not in existing_ids:
            existing_ids.add(it["id"])
            new_items.append(it)
    return new_items


# ----------------------------------------------------------------- e-mail
def li(i, extra=""):
    return ('<li style="margin:6px 0;"><a href="' + i.get("link", "#")
            + '" style="color:#1f2a44;text-decoration:none;"><b>' + i.get("nome", "")
            + '</b></a><br><span style="color:#666;font-size:13px;">' + i.get("inst", "")
            + ' &middot; ' + i.get("prazo", "") + (" &middot; " + i.get("fonte", "") if i.get("fonte") else "")
            + extra + '</span></li>')


def build_email_html(items, new_items, closed_now):
    open_items = sorted([i for i in items if i["status"] == "open"], key=lambda x: x.get("prazoSort", ""))
    prio = [i for i in open_items if parse_date(i.get("prazoSort", "")) and (parse_date(i["prazoSort"]) - TODAY).days <= 45]
    p = ['<div style="font-family:Georgia,serif;max-width:640px;margin:0 auto;color:#1c1c1c;">'
         '<h2 style="color:#1f2a44;border-bottom:3px solid #c8951f;padding-bottom:6px;">'
         'Monitor de Congressos &amp; Publicacoes &mdash; ' + TODAY.strftime("%d/%m/%Y") + '</h2>'
         '<p style="color:#444;font-size:14px;">Ola, Jully! Resumo desta atualizacao.</p>']
    if new_items:
        p.append('<h3 style="color:#8a6406;">Novidades encontradas (' + str(len(new_items)) + ')</h3><ul>')
        p.append("".join(li(i) for i in new_items)); p.append("</ul>")
    if prio:
        p.append('<h3 style="color:#1f2a44;">Prazos nos proximos 45 dias</h3><ul>')
        for i in prio:
            d = (parse_date(i["prazoSort"]) - TODAY).days
            p.append(li(i, ' &middot; <b style="color:#8a6406;">' + ("hoje!" if d == 0 else str(d) + " dias") + '</b>'))
        p.append("</ul>")
    p.append('<h3 style="color:#1f2a44;">Todas as chamadas abertas (' + str(len(open_items)) + ')</h3><ul>')
    p.append("".join(li(i) for i in open_items)); p.append("</ul>")
    if closed_now:
        p.append('<h3 style="color:#8a2b2b;">Encerraram desde a ultima atualizacao</h3><ul>')
        p.append("".join('<li style="color:#888;">' + i.get("nome", "") + '</li>' for i in closed_now)); p.append("</ul>")
    p.append('<p style="font-size:12px;color:#999;margin-top:18px;">Painel completo (com filtros e arquivar) no GitHub Pages. '
             'Atualizacao automatica &middot; segundas e quartas as 7h.</p></div>')
    return "".join(p)


def send_email(html):
    user, pwd, to = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD"), os.environ.get("MAIL_TO")
    if not (user and pwd and to):
        print("[email] credenciais ausentes - pulando envio.")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Monitor de Congressos - " + TODAY.strftime("%d/%m/%Y")
    msg["From"], msg["To"] = user, to
    msg.attach(MIMEText("Abra em HTML.", "plain"))
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(user, pwd)
        s.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
    print("[email] enviado para " + to)


def main():
    data = json.load(open(EVENTS, encoding="utf-8"))
    cfg = json.load(open(SOURCES, encoding="utf-8"))
    items = data.get("items", [])
    existing_ids = set(i["id"] for i in items)
    existing_links = set(norm_link(i.get("link", "")) for i in items)

    closed_now = recompute_status(items)
    try:
        new_items = collect(cfg, existing_links, existing_ids)
    except Exception as e:
        print("[collect] erro geral: " + str(e)); new_items = []
    items.extend(new_items)
    data["items"] = items

    with open(EVENTS, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    counts = {}
    for i in items:
        counts[i["status"]] = counts.get(i["status"], 0) + 1
    with open(LAST, "w", encoding="utf-8") as f:
        json.dump({"timestamp": datetime.datetime.now().isoformat(timespec="minutes"),
                   "total": len(items), "novos": len(new_items),
                   "encerrados_neste_run": len(closed_now), "por_status": counts}, f, ensure_ascii=False, indent=2)
    print("[ok] total=" + str(len(items)) + " novos=" + str(len(new_items)) + " status=" + str(counts))
    try:
        send_email(build_email_html(items, new_items, closed_now))
    except Exception as e:
        print("[email] erro: " + str(e))


if __name__ == "__main__":
    main()

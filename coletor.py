#!/usr/bin/env python3
"""Órbita 0.2 — agregação gratuita para piloto pessoal, sem dependências externas.

Rastreia SOMENTE manchete, URL e metadados RSS. Não republica textos, imagens,
resumos de terceiros nem inventa análises com IA. Uso público/comercial depende de
revisão dos termos e licenças de cada fonte.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, time, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "briefing.json"
# URLs confirmadas no diretório de feeds da Agência Brasil; disponibilidade precisa
# ser validada no ambiente onde o coletor for executado.
FEEDS = [
    ("Agência Brasil — Internacional", "Mundo", "https://agenciabrasil.ebc.com.br/rss/internacional/feed.xml"),
    ("Agência Brasil — Economia", "Brasil", "https://agenciabrasil.ebc.com.br/rss/economia/feed.xml"),
    ("Agência Brasil — Política", "Brasil", "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml"),
    ("Agência Brasil — Geral", "Brasil", "https://agenciabrasil.ebc.com.br/rss/geral/feed.xml"),
    ("Agência Brasil — Cultura", "Interesses", "https://agenciabrasil.ebc.com.br/rss/cultura/feed.xml"),
    ("Agência Brasil — Esportes", "Interesses", "https://agenciabrasil.ebc.com.br/rss/esportes/feed.xml"),
]
TARGETS = [("Mundo",3), ("Brasil",3), ("São Paulo",2), ("Mercado imobiliário",4), ("Interesses",2)]
PATTERNS = {
 "São Paulo": r"\bs[aã]o paulo\b|\bpaulistan[oa]s?\b|\bcapital paulista\b|\bmetro de sp\b|\bmetr[oô] de s[aã]o paulo\b|\bavenida paulista\b|\bpinheiros\b|\bmoema\b|\bbrooklin\b|\bitai[m]?\b",
 "Mercado imobiliário":r"\bim[oó]ve(?:l|is)\b|imobili[aá]ri|habita[cç][aã]o|\bconstru[cç][aã]o civil\b|incorporador|financiamento imobili|mercado residencial|\baluguel\b|\bloca[cç][aã]o\b|\bcondom[ií]nio\b|\bmetro quadrado\b|\bapartamento\b|\burbanismo\b|\barquitetura\b",
 "Interesses":r"f[oó]rmula 1|\bf1\b|automobilismo|gastronomi|restauran|\bturismo\b|\bviagen[sm]\b|\bluxo\b|\bdesign\b|\bgrande pr[eê]mio\b|\bhotelaria\b|\bcircuito\b",
}

def normalize(s):
    return " ".join(unicodedata.normalize("NFKC",s or "").split())

def canonical(url):
    p=urlsplit(url)
    if p.scheme not in ("https","http") or not p.netloc: return None
    # Remover apenas parâmetros de rastreio conhecidos; preservar IDs e slugs.
    q=[(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith("utm_") and k.lower() not in ("fbclid","gclid")]
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),""))

def parse_date(raw):
    if not raw: return None
    try:
        val=parsedate_to_datetime(raw)
    except Exception:
        try: val=datetime.fromisoformat(raw.replace("Z","+00:00"))
        except (ValueError,TypeError): return None
    if not val.tzinfo:val=val.replace(tzinfo=timezone.utc)
    return val.astimezone(timezone.utc)

def node_text(el, name):
    n=el.find(name)
    return normalize("".join(n.itertext())) if n is not None else ""

def parse_rss(raw, source_name, base_cat):
    tree=ET.fromstring(raw)
    # RSS 2.0 and Atom; no external package dependency.
    entries=tree.findall("./channel/item")
    atom=False
    if not entries:
        entries=tree.findall("{http://www.w3.org/2005/Atom}entry")
        atom=True
    out=[]
    for item in entries:
        if atom:
            ns="{http://www.w3.org/2005/Atom}"
            title=node_text(item,ns+"title")
            links=item.findall(ns+"link")
            link=next((x.get("href","") for x in links if x.get("rel","alternate")=="alternate"), "")
            published=node_text(item,ns+"published") or node_text(item,ns+"updated")
        else:
            title=node_text(item,"title")
            link=node_text(item,"link")
            published=node_text(item,"pubDate") or node_text(item,"{http://purl.org/dc/elements/1.1/}date")
        link=canonical(link)
        when=parse_date(published)
        if not (title and link and when):continue
        # Não usar o corpo nem a descrição protegida por direitos autorais.
        out.append({"id":hashlib.sha256(link.encode()).hexdigest()[:16],"title":title[:260],"url":link,"publishedAt":when.isoformat(),"source":source_name.split(" — ")[0],"feed":source_name,"baseCategory":base_cat})
    return out

def classify(article):
    t=article["title"].lower()
    for category in ["Mercado imobiliário","São Paulo","Interesses"]:
        if re.search(PATTERNS[category],t,re.I):
            return category
    return article["baseCategory"] if article["baseCategory"] in ("Mundo","Brasil") else "Brasil"

def select(items, now):
    # Encerra a janela de fatos às 7:30 no fuso local; em execução manual após 8h,
    # também adota o corte para esta edição, sem apresentar novidades como se pré-8h.
    local=now.astimezone(TZ)
    edition_date=local.date()
    cutoff=datetime.combine(edition_date,time(7,30),TZ).astimezone(timezone.utc)
    # Em execução antes das 7:30, só pode usar notícias já publicadas.
    cutoff=min(cutoff,now.astimezone(timezone.utc))
    start=cutoff-timedelta(days=5)
    seen=set(); eligible=[]
    for item in items:
        when=datetime.fromisoformat(item["publishedAt"])
        if when<start or when>cutoff: continue
        title_key=re.sub(r"\W+","",unicodedata.normalize('NFKD',item["title"]).encode('ascii','ignore').decode().lower())
        signature=title_key[:90]
        if item["id"] in seen or signature in seen:continue
        seen.update([item["id"],signature])
        copy={k:v for k,v in item.items() if k!="baseCategory"}
        copy["category"]=classify(item)
        eligible.append(copy)
    eligible.sort(key=lambda a:a["publishedAt"],reverse=True)
    selected=[]; used=set()
    for category,n in TARGETS:
        for article in (a for a in eligible if a["category"]==category and a["id"] not in used):
            if sum(1 for a in selected if a["category"]==category)>=n:break
            selected.append(article);used.add(article["id"])
    # Não completar artificialmente categorias sem cobertura adequada.
    selected.sort(key=lambda a:a["publishedAt"],reverse=True)
    return selected, edition_date.isoformat()

def fetch(url):
    req=Request(url,headers={"User-Agent":"OrbitaPilot/0.2 (+RSS reader, personal testing)","Accept":"application/rss+xml, application/atom+xml, application/xml, text/xml"})
    with urlopen(req,timeout=13) as response:
        data=response.read(1_200_001)
        if len(data)>1_200_000:raise ValueError("Feed excede limite de segurança")
        return data

def build(now=None,fixture=None,out=OUT):
    now=now or datetime.now(timezone.utc)
    stories=[]; warnings=[]; ok=0
    for name,cat,url in FEEDS:
        try:
            raw=Path(fixture).read_bytes() if fixture else fetch(url)
            articles=parse_rss(raw,name,cat)
            if not articles:raise ValueError("RSS vazio ou formato inesperado")
            stories.extend(articles)
            ok+=1
        except Exception as exc:
            warnings.append(f"{name}: {type(exc).__name__} ({str(exc)[:110]})")
    chosen,day=select(stories,now)
    data={"editionDate":day,"timezone":"America/Sao_Paulo","generatedAt":now.isoformat(),"status":"ready" if chosen else "unavailable","sourceFeedsOk":ok,"sourceFeedsTotal":len(FEEDS),"items":chosen,"warnings":warnings,"editorialNote":"Piloto experimental: manchetes e links de RSS. Sem resumos IA ou checagem editorial humana. Não publicar comercialmente antes de validar direitos."}
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    # Nunca sobrescrever uma edição com artigos por uma falha momentânea de rede.
    if not chosen and out.exists():
        try:
            prev=json.loads(out.read_text(encoding="utf-8"))
            if prev.get("items"):
                print("Falha de coleta: edição anterior preservada, com sua data original.",file=sys.stderr)
                return False
        except (ValueError,OSError):pass
    out.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Edição {day}: {len(chosen)} manchetes; feeds OK {ok}/{len(FEEDS)}; erros {len(warnings)}")
    return bool(chosen)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--fixture", help="Arquivo XML para teste offline (NÃO usar com notícias reais)")
    parser.add_argument("--out",default=str(OUT))
    parser.add_argument("--now",help="Data/hora ISO para testes")
    args=parser.parse_args()
    now=datetime.fromisoformat(args.now.replace("Z","+00:00")) if args.now else None
    sys.exit(0 if build(now,args.fixture,args.out) else 1)

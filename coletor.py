#!/usr/bin/env python3
"""Órbita 0.5 — agregação gratuita para piloto pessoal, sem dependências externas.

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
    # Seis RSS públicos da EBC observados como funcionais em 13/10/2026 no GitHub Actions.
    ("Agência Brasil — Internacional", "Mundo", "https://agenciabrasil.ebc.com.br/rss/internacional/feed.xml"),
    ("Agência Brasil — Economia", "Brasil", "https://agenciabrasil.ebc.com.br/rss/economia/feed.xml"),
    ("Agência Brasil — Política", "Brasil", "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml"),
    ("Agência Brasil — Geral", "Brasil", "https://agenciabrasil.ebc.com.br/rss/geral/feed.xml"),
    ("Agência Brasil — Cultura", "Interesses", "https://agenciabrasil.ebc.com.br/rss/cultura/feed.xml"),
    ("Agência Brasil — Esportes", "Interesses", "https://agenciabrasil.ebc.com.br/rss/esportes/feed.xml"),
    ("Agência Câmara — Geral", "Brasil", "https://www.camara.leg.br/noticias/rss/ultimas-noticias"),
    # RSS em avaliação — não foram confirmados pelo GitHub Actions ainda.
    ("Agência SP — Notícias", "São Paulo", "https://www.agenciasp.sp.gov.br/feed/"),
    ("Secovi-SP — Notícias", "Mercado imobiliário", "https://secovi.com.br/feed/"),
    ("Sebrae-SP — Notícias", "Brasil", "https://sp.agenciasebrae.com.br/feed/"),
]
# API oficial sem autenticação; retorna JSON, não RSS.
API_SOURCES = [
    ("IBGE — Agência de Notícias", "Brasil", "https://servicodados.ibge.gov.br/api/v3/noticias/?qtd=30"),
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
            link=next((x.get("href","") for x in links if x.get("rel","alternate")=="alternate"), "") or next((x.get("href","") for x in links), "")
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


def parse_ibge_news(raw, source_name="IBGE — Agência de Notícias", base_cat="Brasil"):
    """Interpreta JSON da API oficial sem copiar introduções ou artigos.

    Os horários publicados sem timezone são interpretados como horário de Brasília.
    """
    payload=json.loads(raw)
    entries=payload.get("items",[]) if isinstance(payload,dict) else []
    if not isinstance(entries,list): raise ValueError("IBGE: items não é lista")
    result=[]
    for entry in entries:
        if not isinstance(entry,dict):continue
        title=normalize(entry.get("titulo", ""))
        link=canonical(entry.get("link", ""))
        raw_date=entry.get("data_publicacao", "")
        dt=None
        if isinstance(raw_date,str):
            for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt=datetime.strptime(raw_date.strip(),fmt).replace(tzinfo=TZ).astimezone(timezone.utc)
                    break
                except ValueError:pass
            if dt is None: dt=parse_date(raw_date)
        if not (title and link and dt):continue
        result.append({"id":hashlib.sha256(link.encode()).hexdigest()[:16],
                       "title":title[:260],"url":link,"publishedAt":dt.isoformat(),
                       "source":"IBGE","feed":source_name,"baseCategory":base_cat})
    return result

def classify(article):
    t=article["title"].lower()
    for category in ["Mercado imobiliário","São Paulo","Interesses"]:
        if re.search(PATTERNS[category],t,re.I):
            return category
    base=article.get("baseCategory", "Brasil")
    if base=="São Paulo":
        # Uma nota estadual de saúde não é automaticamente notícia da cidade.
        return "São Paulo" if re.search(PATTERNS["São Paulo"],t,re.I) else "Brasil"
    if base=="Mercado imobiliário":
        return "Mercado imobiliário" if re.search(PATTERNS["Mercado imobiliário"],t,re.I) else "Brasil"
    if article.get("feed", "").startswith("BBC News Brasil"):
        # O feed da BBC contém notícias nacionais e internacionais.
        if re.search(r"\bbrasil\b|brasileir|\blula\b|\bbolsonaro\b|\bstf\b|\bs[aã]o paulo\b",t,re.I):
            return "Brasil"
    return base if base in ("Mundo","Brasil") else "Brasil"

# A filtragem não usa IA. São regras iniciais, transparentes e ajustáveis
# para reduzir manchetes pouco úteis no piloto imobiliário.
BLOCKED_TOPICS = re.compile(
    r"mega.sena|loto.f[aá]cil|lotomania|\bquina\b|timemania|lot[eé]rica|"
    r"pr[eê]mio acumulado|\bapostas?\b|"
    r"brasileir[aã]o|copa do brasil|\bgols?\b|\bplacar\b|"
    r"\bfutebol\b|\bferrovi[aá]ria\b|\bbragantino\b|"
    r"\bs[eé]rie [ab]\b|\bcampeonato paulista\b",
    re.I,
)
F1_TOPICS = re.compile(r"f[oó]rmula 1|\bf1\b|\bgrande pr[eê]mio\b|\bformula one\b", re.I)
ECONOMY_TOPICS = re.compile(
    r"juros|\bselic\b|\bipca\b|infla[cç][aã]o|c[aâ]mbio|\bd[oó]lar\b|"
    r"investiment|banco central|\bpib\b|mercado financeir|\bbolsa\b|"
    r"impostos?|tribut|\bfiscal\b|cr[eé]dito|\beconomia\b|"
    r"neg[oó]cios|exporta[cç]|importa[cç]|empresas?|empreendedor|\bsinapi\b|\bibge\b|\bind[uú]stria\b|\bconsumo\b",
    re.I,
)
PUBLIC_IMPACT_TOPICS = re.compile(
    r"elei[cç]|democracia|governo|president|congresso|senado|"
    r"supremo|\bstf\b|reforma|pol[ií]tica|guerra|conflit|"
    r"san[cç][oõ]es|geopol[ií]tica|diplomac|acordo internacional|"
    r"crise|seguran[cç]a p[uú]blica|transi[cç][aã]o energ[eé]tica",
    re.I,
)
LOCAL_CONTEXT_TOPICS = re.compile(
    r"mobilidade|infraestrutura|urbanismo|\bmetr[oô]\b|"
    r"transport|prefeitura|zoneamento|requalifica[cç]|urban[aio]",
    re.I,
)


def is_relevant(item):
    title=item["title"]
    # No piloto, outros esportes e sorteios ficam fora, mesmo sendo recentes.
    if F1_TOPICS.search(title):
        return True
    if BLOCKED_TOPICS.search(title):
        return False
    if item.get("feed", "").endswith("— Esportes"):
        return False
    return True


def relevance_score(item, cutoff):
    title=item["title"]
    category=item["category"]
    # Um assunto setorial ou local ganha prioridade sobre variedade genérica.
    score={"Mercado imobiliário": 12, "São Paulo": 9,
           "Mundo": 4, "Brasil": 3, "Interesses": 6}.get(category,0)
    if ECONOMY_TOPICS.search(title): score+=8
    if PUBLIC_IMPACT_TOPICS.search(title): score+=5
    if LOCAL_CONTEXT_TOPICS.search(title): score+=4
    if F1_TOPICS.search(title): score+=7
    if category=="Interesses" and re.search(PATTERNS["Interesses"], title, re.I): score+=4
    # Fontes especialistas ajudam, mas não devem vencer notícias nacionais relevantes só pela origem.
    hours=(cutoff-datetime.fromisoformat(item["publishedAt"])).total_seconds()/3600
    # Atualidade conta, mas não deve superar a relevância para o usuário.
    score-=hours/10
    return score


def select(items, now):
    # Edição de 08:00: somente fatos divulgados até 07:30, horário de SP.
    local=now.astimezone(TZ)
    edition_date=local.date()
    cutoff=datetime.combine(edition_date,time(7,30),TZ).astimezone(timezone.utc)
    cutoff=min(cutoff,now.astimezone(timezone.utc))
    # Evitar selecionar notícias de quatro ou cinco dias atrás só para completar uma cota.
    start=cutoff-timedelta(hours=48)
    seen=set(); eligible=[]
    for item in items:
        when=datetime.fromisoformat(item["publishedAt"])
        if when<start or when>cutoff: continue
        title_key=re.sub(r"\W+","",unicodedata.normalize('NFKD',item["title"]).encode('ascii','ignore').decode().lower())
        signature=title_key[:90]
        if item["id"] in seen or signature in seen: continue
        seen.update([item["id"],signature])
        if not is_relevant(item): continue
        copy={k:v for k,v in item.items() if k!="baseCategory"}
        copy["category"]=classify(item)
        eligible.append(copy)
    # Selecionar os melhores itens por editoria e ordenar os destaques pela relevância.
    eligible.sort(key=lambda a:(relevance_score(a,cutoff),a["publishedAt"]),reverse=True)
    selected=[]; used=set()
    # Portão mínimo de relevância: evita preencher a edição com celebridades, loteria,
    # notas burocráticas ou saúde genérica só para alcançar a meta de 14 itens.
    # Um fato público relevante da noite anterior não deve ser descartado por uma diferença marginal de pontuação.
    minimum={"Mundo":6, "Brasil":6, "São Paulo":9, "Mercado imobiliário":10, "Interesses":8}
    for category, n in TARGETS:
        count=0
        for article in eligible:
            if count>=n: break
            if article["category"]!=category or article["id"] in used: continue
            if relevance_score(article,cutoff)<minimum[category]: continue
            selected.append(article); used.add(article["id"]); count+=1
    selected.sort(key=lambda a:(relevance_score(a,cutoff),a["publishedAt"]),reverse=True)
    return selected, edition_date.isoformat()

def fetch(url):
    req=Request(url,headers={"User-Agent":"OrbitaPilot/0.5 (+RSS reader, personal testing)","Accept":"application/rss+xml, application/atom+xml, application/xml, text/xml"})
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
            if not articles: raise ValueError("Feed vazio, sem datas ou em formato inesperado")
            stories.extend(articles)
            ok+=1
            print(f"[FEED OK] {name}: {len(articles)} entradas", flush=True)
        except Exception as exc:
            message=f"{name}: {type(exc).__name__} ({str(exc)[:110]})"
            warnings.append(message)
            print(f"[FEED FALHOU] {message}",file=sys.stderr,flush=True)
    for name,cat,url in (API_SOURCES if not fixture else []):
        try:
            raw=Path(fixture).read_bytes() if fixture else fetch(url)
            articles=parse_ibge_news(raw,name,cat)
            if not articles: raise ValueError("API vazia ou formato inesperado")
            stories.extend(articles)
            ok+=1
            print(f"[API OK] {name}: {len(articles)} entradas",flush=True)
        except Exception as exc:
            message=f"{name}: {type(exc).__name__} ({str(exc)[:110]})"
            warnings.append(message)
            print(f"[API FALHOU] {message}",file=sys.stderr,flush=True)
    local=now.astimezone(TZ)
    editorial_cutoff=min(
        datetime.combine(local.date(),time(7,30),TZ).astimezone(timezone.utc),
        now.astimezone(timezone.utc)
    )
    seen_recent=0; recent_unblocked=0
    for item in stories:
        when=datetime.fromisoformat(item['publishedAt'])
        if editorial_cutoff-timedelta(hours=48)<=when<=editorial_cutoff:
            seen_recent+=1
            if is_relevant(item): recent_unblocked+=1
    chosen,day=select(stories,now)
    coverage=[{"category":category,"target":n,"count":sum(a["category"]==category for a in chosen)} for category,n in TARGETS]
    cutoff_sp=editorial_cutoff.astimezone(TZ).strftime('%d/%m/%Y %H:%M')
    print(f"[DIAGNÓSTICO] Fuso SP; corte editorial {cutoff_sp}; feeds OK {ok}/{len(FEEDS)+len(API_SOURCES)}; "
          f"entradas totais {len(stories)}; últimas 48h antes do corte {seen_recent}; "
          f"sem bloqueios temáticos {recent_unblocked}; selecionadas {len(chosen)}", flush=True)
    print("[EDITORIAS] "+", ".join(f"{x['category']}={x['count']}" for x in coverage),flush=True)
    data={"editionDate":day,"timezone":"America/Sao_Paulo","generatedAt":now.isoformat(),"status":"ready" if chosen else "unavailable","sourceFeedsOk":ok,"sourceFeedsTotal":len(FEEDS)+len(API_SOURCES),"items":chosen,"coverage":coverage,"warnings":warnings,"editorialNote":"Piloto experimental: manchetes, URLs e datas de RSS e API pública, com filtro de relevância por regras. Sem resumos IA ou checagem editorial humana. Acesso público não implica autorização para redistribuição comercial; licenças precisam ser validadas."}
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    # Quando há fontes válidas mas nenhum fato supera os critérios editoriais,
    # a execução técnica funciona: manter a edição anterior é uma decisão editorial.
    if not chosen and out.exists():
        try:
            prev=json.loads(out.read_text(encoding="utf-8"))
            if prev.get("items"):
                print("[SEM NOVA EDIÇÃO] Edição anterior preservada, com sua data original.",flush=True)
                if not ok:
                    print("[ERRO] Todas as fontes falharam; é necessário corrigir os feeds.",file=sys.stderr,flush=True)
                else:
                    print("[AVISO] Houve feeds disponíveis, mas nenhuma notícia passou pelo corte/filtro. "+
                          "Isto NÃO significa que novas notícias foram publicadas.",flush=True)
                return ok>0
        except (ValueError,OSError): pass
    out.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"[RESULTADO] Edição {day}: {len(chosen)} manchetes; feeds OK {ok}/{len(FEEDS)+len(API_SOURCES)}; erros {len(warnings)}",flush=True)
    if not ok:
        print("[ERRO] Nenhuma fonte forneceu RSS válido. Edição indisponível.",file=sys.stderr,flush=True)
        return False
    if not chosen:
        print("[AVISO] Nenhuma notícia elegível; arquivo marcado como indisponível, sem inventar manchetes.",flush=True)
    return True

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--fixture", help="Arquivo XML para teste offline (NÃO usar com notícias reais)")
    parser.add_argument("--out",default=str(OUT))
    parser.add_argument("--now",help="Data/hora ISO para testes")
    args=parser.parse_args()
    now=datetime.fromisoformat(args.now.replace("Z","+00:00")) if args.now else None
    sys.exit(0 if build(now,args.fixture,args.out) else 1)

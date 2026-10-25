#!/usr/bin/env python3
"""Órbita 0.7.3 — prévia isolada da curadoria gratuita (sem publicação).

Rastreia SOMENTE manchete, URL e metadados RSS. Não republica textos, imagens,
resumos de terceiros nem inventa análises com IA. Uso público/comercial depende de
revisão dos termos e licenças de cada fonte.
"""
from __future__ import annotations
import html
import argparse
import gzip
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
OUT = ROOT / "data" / "briefing_preview_073.json"
# A prévia NÃO altera data/briefing.json; o fluxo 0.5.1 permanece intacto.
# URLs confirmadas no diretório de feeds da Agência Brasil; disponibilidade precisa
# ser validada no ambiente onde o coletor for executado.
FEEDS = [
    # Fontes verificadas nas auditorias realizadas no GitHub Actions em 14/10/2026.
    # Validação técnica de RSS não confirma licença comercial nem ausência de paywall.
    ("Agência Brasil — Internacional", "Mundo", "https://agenciabrasil.ebc.com.br/rss/internacional/feed.xml"),
    ("G1 — Mundo", "Mundo", "https://g1.globo.com/rss/g1/mundo/"),
    ("Agência Brasil — Economia", "Brasil", "https://agenciabrasil.ebc.com.br/rss/economia/feed.xml"),
    ("Agência Brasil — Política", "Brasil", "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml"),
    ("G1 — Política", "Brasil", "https://g1.globo.com/rss/g1/politica/"),
    ("CNN Brasil", "Brasil", "https://admin.cnnbrasil.com.br/feed/"),
    ("InfoMoney", "Brasil", "https://www.infomoney.com.br/feed/"),
    ("Sebrae-SP — Notícias", "Brasil", "https://sp.agenciasebrae.com.br/feed/"),
    ("Diário do Transporte — Notícias", "São Paulo", "https://diariodotransporte.com.br/feed/"),
    # FONTES EXPERIMENTAIS: endereços públicos encontrados na pesquisa, mas
    # ainda sem teste de disponibilidade RSS na automação do usuário.
    ("Diário do Transporte — Metropolitano SP", "São Paulo", "https://diariodotransporte.com.br/category/metropolitano-sp/feed/"),
    ("Agência Mural — Grande São Paulo", "São Paulo", "https://agenciamural.org.br/feed/"),
    ("Jornal da USP — Notícias", "São Paulo", "https://jornal.usp.br/feed/"),
    # Endereços retornaram content-type RSS na pesquisa de 25/10; só o teste
    # manual no GitHub confirmará leitura das entradas e datas. Não declarados aprovados.
    ("Metrópoles — São Paulo", "São Paulo", "https://www.metropoles.com/sao-paulo/feed"),
    ("Metrô de São Paulo — Notícias", "São Paulo", "https://www.metro.sp.gov.br/feed/"),
    ("SindusCon-SP — Imobiliário", "Mercado imobiliário", "https://sindusconsp.com.br/noticias/imobiliario/feed/"),
    ("Secovi-SP — Notícias", "Mercado imobiliário", "https://secovi.com.br/feed/"),
    ("CBIC — Notícias", "Mercado imobiliário", "https://cbic.org.br/feed/"),
    ("ArchDaily Brasil — Arquitetura", "Interesses", "https://feeds.feedburner.com/ArchdailyBR"),
    ("Motorsport Brasil — Fórmula 1", "Interesses", "https://motorsport.uol.com.br/rss/f1/news/"),
    ("Prazeres da Mesa — Gastronomia", "Interesses", "https://www.prazeresdamesa.com.br/feed/"),
    ("Melhores Destinos — Viagens", "Interesses", "https://www.melhoresdestinos.com.br/feed/"),
    ("Forbes Brasil — Geral", "Interesses", "https://forbes.com.br/feed/"),
    ("Harper's Bazaar Brasil — Geral", "Interesses", "https://harpersbazaar.uol.com.br/feed/"),
    ("Hotelier News — Geral", "Interesses", "https://hoteliernews.com.br/feed/"),
]
# Não incluir fontes com erro 500/404, páginas HTML em vez de RSS ou feeds
# sem datas parseáveis (ex.: Mobilize, pendente de diagnóstico). 
# API oficial sem autenticação; retorna JSON, não RSS.
API_SOURCES = [
    ("IBGE — Agência de Notícias", "Brasil", "https://servicodados.ibge.gov.br/api/v3/noticias/?qtd=30"),
]

TARGETS = [("Mundo",2), ("Brasil",2), ("São Paulo",2), ("Mercado imobiliário",3), ("Interesses",5)]
PATTERNS = {
 "São Paulo": r"\bs[aã]o paulo\b|\bpaulistan[oa]s?\b|\bcapital paulista\b|\bmetro de sp\b|\bmetr[oô] de s[aã]o paulo\b|\bavenida paulista\b|\bpinheiros\b|\bmoema\b|\bbrooklin\b|\bitaim\b",
 "Mercado imobiliário":r"\bim[oó]ve(?:l|is)\b|imobili[aá]ri|habita[cç][aã]o|\bconstru[cç][aã]o civil\b|incorporador|financiamento imobili|mercado residencial|\baluguel\b|\bloca[cç][aã]o\b|\bcondom[ií]nio\b|\bmetro quadrado\b|\bapartamento\b|\burbanismo\b|\barquitetura\b|lan[cç]ament[oa]s? residencia|empreendiment[oa]s? imobili|setor imob",
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
    return normalize(html.unescape("".join(n.itertext()))) if n is not None else ""

def parse_rss(raw, source_name, base_cat):
    root=ET.fromstring(normalize_response_bytes(raw))
    atom="{http://www.w3.org/2005/Atom}"
    rss1="{http://purl.org/rss/1.0/}"
    dc="{http://purl.org/dc/elements/1.1/}"
    dcterms="{http://purl.org/dc/terms/}"
    root_tag=root.tag.rsplit('}',1)[-1].lower()
    if root_tag=='feed':
        entries=root.findall(atom+'entry')
    elif root_tag=='rdf':
        entries=root.findall(rss1+'item') or root.findall('item')
    elif root_tag=='rss':
        entries=root.findall('./channel/item')
    else:
        raise ValueError('XML não é RSS/Atom reconhecível')
    out=[]
    for item in entries:
        if root_tag=='feed':
            title=node_text(item,atom+'title')
            links=item.findall(atom+'link')
            link=(next((x.get('href','') for x in links if x.get('rel','alternate')=='alternate'),'')
                  or next((x.get('href','') for x in links if x.get('rel') in (None,'alternate')),''))
            published=node_text(item,atom+'published') or node_text(item,atom+'updated')
        else:
            prefix=rss1 if root_tag=='rdf' else ''
            title=node_text(item,prefix+'title') or node_text(item,'title')
            link=node_text(item,prefix+'link') or node_text(item,'link')
            published=(node_text(item,'pubDate') or node_text(item,dc+'date')
                       or node_text(item,dcterms+'issued') or node_text(item,dcterms+'created')
                       or node_text(item,atom+'updated'))
        link=canonical(link)
        when=parse_date(published)
        if not (title and link and when): continue
        # Copyright: manchete e metadados, sem descrição, corpo ou imagens.
        out.append({'id':hashlib.sha256(link.encode()).hexdigest()[:16],
                    'title':title[:260], 'url':link, 'publishedAt':when.isoformat(),
                    'source':source_name.split(' — ')[0], 'feed':source_name,
                    'baseCategory':base_cat})
    return out


def normalize_response_bytes(raw):
    """Alguns servidores devolvem gzip (1f 8b) mesmo sem pedido explícito."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
        if len(raw)>5_000_000: raise ValueError("Conteúdo descompactado excede limite")
    return raw


def parse_ibge_news(raw, source_name="IBGE — Agência de Notícias", base_cat="Brasil"):
    """Interpreta JSON da API oficial sem copiar introduções ou artigos.

    Os horários publicados sem timezone são interpretados como horário de Brasília.
    """
    payload=json.loads(normalize_response_bytes(raw))
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

# O feed de uma revista generalista não prova que cada artigo é sobre luxo.
# Critérios explícitos minimizam falsos positivos por rótulo do veículo.
LUXURY_SIGNALS = re.compile(
    r"\bluxo\b|\bluxury\b|\balto padr[aã]o\b|\bjoalheria\b|\brelojoaria\b|"
    r"\brolex\b|\bpatek\b|\baudemars\b|\bcartier\b|\bherm[eè]s\b|"
    r"\blouis vuitton\b|\bchanel\b|\bdior\b|\bprada\b|\bgucci\b|"
    r"\bferrari\b|\blamborghini\b|\bbentley\b|\brolls.royce\b|"
    r"\bjato executivo\b|\biate\b|\byacht\b|\bhotel de luxo\b|"
    r"\bhotel cinco estrelas\b|\bfour seasons\b|\bfasano\b|\brosewood\b|"
    r"\bmandarin oriental\b|\balta gastronomia\b|\bmichelin\b|"
    r"\bmans[aã]o\b|\bhotel boutique\b",re.I)
CITY_SIGNALS = re.compile(
    r"\bs[aã]o paulo\b|\bpaulistan[oa]s?\b|\bcapital paulista\b|"
    r"\bprefeitura de sp\b|\bmetr[oô] de sp\b|\bcptm\b|"
    r"\bpinheiros\b|\bmoema\b|\bitaim(?: bibi)?\b|\bbrooklin\b|"
    r"\bjardins\b|\bvila mariana\b|\bibirapuera\b|\bfaria lima\b|"
    r"\bavenida paulista\b|\bmarginal (?:tiet[eê]|pinheiros)\b|"
    r"\bbel[a]? vista\b|\bpara[ií]so\b|\blinha [0-9]+[- ](?:azul|verde|vermelha|amarela|lil[aá]s|rubi|esmeralda|safira|diamante|coral)\b",re.I)

LOCAL_CITY_CONTEXT = re.compile(
    r"\bmetr[oô]\b|\bcptm\b|\besta[cç][aã]o\b|\bmobilidade\b|"
    r"\btr[aâ]nsito\b|\btransportes?\b|\b[oô]nibus\b|"
    r"\bprefeitura\b|\bmunic[ií]pio\b|\bcapital\b|"
    r"\brua\b|\bavenida\b|\bbairro\b|\bciclovia\b|"
    r"\bviaduto\b|\bzoneamento\b|\burbanismo\b|"
    r"\bespa[cç]o p[uú]blico\b|\blinha [0-9]+\b",re.I)
STATE_CONTEXT = re.compile(
    r"\bgoverno do estado\b|\bgoverno de s[aã]o paulo\b|\binterior paulista\b|"
    r"\bregi[aã]o de campinas\b|\bmunic[ií]pios do estado\b|"
    r"\bagricultura paulista\b|\bestadual\b",re.I)

# Cobertura metropolitana não é automaticamente 'cidade de São Paulo'.
# Nomes de municípios vizinhos exigem outro indício explícito da capital.
OTHER_CITY_ONLY = re.compile(
    r"\bguarulhos\b|\bosasco\b|\bsanto andr[eé]\b|"
    r"\bs[aã]o bernardo(?: do campo)?\b|\bs[aã]o caetano(?: do sul)?\b|"
    r"\bdiadema\b|\bbarueri\b|\bcarapicu[ií]ba\b|"
    r"\bcampinas\b|\bsantos\b|\bguaruj[aá]\b|"
    r"\bribeir[aã]o preto\b|\bsorocaba\b|\bjundia[ií]\b",
    re.I,
)
CITY_EXPLICIT = re.compile(
    r"\bcapital paulista\b|\bprefeitura de (?:s[aã]o paulo|sp)\b|"
    r"\bcidade de s[aã]o paulo\b|\bmunic[ií]pio de s[aã]o paulo\b|"
    r"\bsubprefeitura\b|\bpaulistan[oa]s?\b|"
    r"\bmetr[oô] de (?:s[aã]o paulo|sp)\b|"
    r"\bpinheiros\b|\bmoema\b|\bitaim bibi\b|\bbrooklin\b|"
    r"\bjardins\b|\bvila mariana\b|\bibirapuera\b|\bfaria lima\b|"
    r"\bavenida paulista\b|\bmarginal (?:tiet[eê]|pinheiros)\b|"
    r"\bzona (?:leste|oeste|norte|sul) de s[aã]o paulo\b|"
    r"\blinha [0-9]+[- ](?:azul|verde|vermelha|amarela|lil[aá]s|rubi|esmeralda|safira|diamante|coral|laranja|ouro|prata)\b",
    re.I,
)

def is_city_story(title):
    # Capital ≠ estado ≠ região metropolitana; conservador quando ambíguo.
    has_explicit=bool(CITY_EXPLICIT.search(title))
    has_neighbor=bool(OTHER_CITY_ONLY.search(title))
    if has_neighbor:
        # A presença de uma linha de trem não basta para transformar uma notícia
        # sobre Osasco ou Guarulhos em notícia do município de São Paulo.
        local_municipality = re.search(
            r"\bcapital paulista\b|\bprefeitura de (?:s[aã]o paulo|sp)\b|"
            r"\bcidade de s[aã]o paulo\b|\bavenida paulista\b|"
            r"\bpinheiros\b|\bmoema\b|\bitaim bibi\b|\bbrooklin\b|"
            r"\bvila mariana\b|\bfaria lima\b", title, re.I)
        if not local_municipality:
            return False
    if has_explicit:
        return True
    if STATE_CONTEXT.search(title):
        return False
    # Sem contexto municipal, "São Paulo" pode ser o estado, o time ou a cidade.
    return bool(re.search(r"\bs[aã]o paulo\b",title,re.I) and
                LOCAL_CITY_CONTEXT.search(title))

# 0.7.3: Uma referência à Avenida Paulista não transforma uma decisão
# eleitoral FEDERAL em notícia da capital. O próprio tema deve ser municipal.
NATIONAL_POLITICS = re.compile(
    r"\btse\b|tribunal superior eleitoral|\bstf\b|supremo tribunal federal|"
    r"elei[cç][oõ]es? presidenciais?|\bfake news\b|"
    r"\b(?:lula|bolsonaro)\b|congresso nacional", re.I)
MUNICIPAL_DECISION = re.compile(
    r"prefeitura de (?:s[aã]o paulo|sp)|\bc[aâ]mara municipal\b|"
    r"\bvereador(?:es)?\b|\bplano diretor\b|\bzoneamento\b|"
    r"\bopera[cç][aã]o urbana\b|\bsubprefeitura\b",re.I)
ORIGINAL_CITY_STORY = is_city_story

def is_city_story(title):
    if NATIONAL_POLITICS.search(title) and not MUNICIPAL_DECISION.search(title):
        return False
    return ORIGINAL_CITY_STORY(title)

# Feeds de abrangência da capital com manchetes às vezes sem 'São Paulo'.
# Nesses casos confiamos no contexto do órgão, mas nunca em municípios vizinhos.
METRO_OFFICIAL = 'metrô de são paulo — notícias'
METRO_LOCAL_TOPICS = re.compile(
    r"\bmetr[oô]\b|\besta[cç][oõ]es?\b|\blinha [0-9]+\b|"
    r"\btrens?\b|\bbilhetes?\b|\bpassagens?\b|"
    r"\brede metrovi[aá]ria\b",re.I)

def is_capital_news(item):
    title=item['title']
    if is_city_story(title):return True
    feed=item.get('feed','').lower()
    if feed==METRO_OFFICIAL and METRO_LOCAL_TOPICS.search(title):
        if OTHER_CITY_ONLY.search(title) or NATIONAL_POLITICS.search(title):return False
        return True
    return False

FOREIGN_MARKET = re.compile(
    r"\bbolsas? (?:da|de|do|na|no) (?:[aá]sia|europa|china|jap[aã]o|"
    r"estados unidos|eua)\b|\b(?:wall street|nasdaq|dow jones|nikkei|"
    r"hang seng|shanghai composite|s&p 500)\b|"
    r"\b(?:mercados? asi[aá]ticos?|a[cç][oõ]es? asi[aá]ticas?)\b",re.I)
BRAZIL_MARKET_ANCHOR = re.compile(
    r"\bbrasil\b|\bbrasileir[oa]s?\b|\bibovespa\b|"
    r"\bb3\b|\bmercado brasileiro\b|\bbolsa brasileira\b|"
    r"\br\$\b",re.I)

def is_foreign_market_story(title):
    return bool(FOREIGN_MARKET.search(title) and not BRAZIL_MARKET_ANCHOR.search(title))

SECTOR_FEED = re.compile(r"\b(?:secovi|cbic|sinduscon)\b",re.I)
SECTOR_STRONG = re.compile(
    r"imobili[aá]ri|im[oó]ve(?:l|is)|\bhabita[cç][aã]o\b|"
    r"incorporador|\bconstru[cç][aã]o civil\b|\bconstrutoras?\b|"
    r"\bcondom[ií]nios?\b|\bcr[eé]dito habitacional\b|"
    r"\bfinanciamentos?\b|\blan[cç]amentos? residencia|"
    r"\bvendas? residencia|\balugu[eé]is?\b|\bloca[cç][aã]o\b|"
    r"\bpre[cç]os? residencia|\bpre[cç]o por metro quadrado\b|"
    r"\bcusto unit[aá]rio b[aá]sico\b|\bcub\b|\bincc\b|"
    r"\bzoneamento\b|\blicenciamento\b|\bpré.vistoria\b|"
    r"\bvistorias?\b|\brequalifica[cç][aã]o\b|"
    r"\bplano diretor\b|\buso e ocupa[cç][aã]o do solo\b|"
    r"\bcadastro imobili[aá]rio\b|\bterreno[s]?\b|"
    r"\bloteamentos?\b|\bempreendimentos? residencia|"
    r"\bmercado residencial\b|\bpre[cç]os? de venda\b", re.I)
SECTOR_LOW_VALUE = re.compile(r"\bposse da diretoria\b|\banivers[aá]rio\b|"
                              r"\bconfraterniza[cç]\b|\bhomenagem\b",re.I)

def is_sector_story(item):
    title=item['title']
    if not SECTOR_FEED.search(item.get('feed','')):return False
    return bool(SECTOR_STRONG.search(title) and not SECTOR_LOW_VALUE.search(title))

# Turismo NÃO é qualquer menção à palavra viagem: deslocamentos do papa,
# de ministros ou diplomatas permanecem na editoria de origem.
TRAVEL_SUBJECT = re.compile(
    r"\bturismo\b|\bturistas?\b|\bpassagens? a[eé]reas?\b|"
    r"\bpassagens? de avi[aã]o\b|\bvoos?\b|\bcompanhias? a[eé]reas?\b|"
    r"\baeroportos?\b|\bdestinos? tur[ií]sticos?\b|\broteiros? tur[ií]sticos?\b|"
    r"\bhospedagens?\b|\bresorts?\b|\bcruzeiros?\b|\bmilhas? a[eé]reas?\b|"
    r"\bhot[eé]is?\b|\bviagens? de f[eé]rias\b|\bviajar de f[eé]rias\b", re.I)
OFFICIAL_TRAVEL = re.compile(
    r"\b(?:papa|pont[ií]fice|presidente|primeiro.ministro|chanceler|"
    r"deputad[oa]|senador[ae]?|ministro[s]?)\b.{0,65}\b(?:viaj\w*|visita|desloca\w*)\b|"
    r"\b(?:viagem|visita)\b.{0,65}\b(?:papa|pont[ií]fice|presidente|"
    r"primeiro.ministro|chanceler|ministro[s]?)\b", re.I)

def interest_topic(article):
    feed=article.get('feed','').lower()
    title=article.get('title','')
    if 'motorsport' in feed or F1_TOPICS.search(title): return 'Fórmula 1'
    if 'archdaily' in feed or re.search(r'\barquitetura\b|\bdesign de interiores\b',title,re.I): return 'Arquitetura e design'
    if 'prazeres da mesa' in feed or re.search(r'\bgastronomi\w*|\brestaurante[s]?\b|\bchef\b',title,re.I): return 'Gastronomia'
    if LUXURY_SIGNALS.search(title): return 'Mercado de luxo'
    if 'melhores destinos' in feed and not OFFICIAL_TRAVEL.search(title): return 'Viagens'
    if TRAVEL_SUBJECT.search(title) and not OFFICIAL_TRAVEL.search(title): return 'Viagens'
    return None

def classify(article):
    title=article['title']
    feed=article.get('feed','').lower()
    base=article.get('baseCategory','Brasil')
    # A origem tem relevância, mas nunca substitui o TEMA principal.
    curated_interest=('archdaily','motorsport','prazeres da mesa','melhores destinos',
                      'forbes','harper','hotelier')
    if any(f in feed for f in curated_interest):
        return 'Interesses' if interest_topic(article) else 'Brasil'
    if is_sector_story(article):return 'Mercado imobiliário'
    # Manchete de política nacional com nome de bairro não é São Paulo local.
    if NATIONAL_POLITICS.search(title) and not MUNICIPAL_DECISION.search(title):
        if base=='Mundo':return 'Mundo'
        return 'Brasil'
    # Índices estrangeiros não devem ocupar a vaga de economia brasileira.
    if is_foreign_market_story(title):return 'Mundo'
    if re.search(PATTERNS['Mercado imobiliário'],title,re.I):
        return 'Mercado imobiliário'
    if base=='Mercado imobiliário':return 'Brasil'
    if base=='São Paulo':
        return 'São Paulo' if is_capital_news(article) else 'Brasil'
    if F1_TOPICS.search(title):return 'Interesses'
    if is_city_story(title) and base!='Mundo':return 'São Paulo'
    if interest_topic(article):return 'Interesses'
    if base=='Interesses':return 'Brasil'
    if article.get('feed','').startswith('BBC News Brasil'):
        if re.search(r'\bbrasil\b|brasileir|\blula\b|\bstf\b',title,re.I):return 'Brasil'
    return base if base in ('Mundo','Brasil') else 'Brasil'

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
# Só as manchetes que indicam um fato relevante entram na edição.
GLOBAL_IMPACT_TOPICS = re.compile(
    r"\bargentina\b|\bmilei\b|\bestados unidos\b|\beua\b|"
    r"\bchina\b|\br[uú]ssia\b|\bucr[aâ]nia\b|\bisrael\b|\bir[aã]\b|"
    r"\beuropa\b|\buni[aã]o europeia\b|\bonu\b|\botan\b|\bmercosul\b|"
    r"\btrump\b|\bputin\b|\bg20\b|\bfmi\b|\bbanco mundial\b|"
    r"deporta[cç]|migra[cç]|tarifas? comerciais?|com[eé]rcio internacional|"
    r"direitos humanos|mudan[cç]as? clim[aá]ticas?|desastre natural|acordo de paz",
    re.I,
)
LOCAL_CHANGE_TOPICS = re.compile(
    r"inaugura|nova linha|nova esta[cç][aã]o|obra|mobilidade|"
    r"transporte|urbanismo|zoneamento|infraestrutura|aprova|licen[cç]a",
    re.I,
)
SECTOR_CONTEXT_TOPICS = re.compile(
    r"mercado imob|pre[cç]os? dos im[oó]veis|vendas? de im[oó]veis|"
    r"lan[cç]amentos? residencia|cr[eé]dito imobili[aá]rio|"
    r"financiamento imobili|setor imob|constru[cç][aã]o civil|"
    r"loca[cç][aã]o residencial|investiment.*im[oó]v|"
    r"valoriza[cç][aã]o imobili[aá]ria",
    re.I,
)


# Exclui publicidade, curiosidades e chamadas de eventos sem fato de impacto.
# Regras conservadoras para não deixar uma manchete promocional passar só
# por mencionar F1, construção, marcas de luxo ou um chef famoso.
PROMOTIONAL = re.compile(
    r"miniaturas? colecion[aá]veis?|\bcolecion[aá]veis\b|"
    r"\bpromo[cç][aã]o\b|\bdesconto[s]?\b|\bcupon[s]?\b|"
    r"\bconcurso cultural\b|\bsorteio[s]?\b|"
    r"pit stop perfeito|\bbrinde[s]?\b|"
    r"\bparceria comercial\b|\bmerchandising\b",re.I,
)
LOW_IMPACT_CURIOSITY = re.compile(
    r"confunde .* com (?:marido|esposa)|\bgafe\b|"
    r"\bviraliza\b|\bviralizou\b|"
    r"\blook\b.*\bpresidente\b|\bfofoca\b",re.I,
)
EVENT_ANNOUNCEMENT = re.compile(
    r"\b(?:congresso|encontro|semin[aá]rio|feira|f[oó]rum|f[oó]runs?|"
    r"confer[eê]ncia|workshop|summit|conven[cç][aã]o|expo|evento|"
    r"immobi connection)\b.{0,140}\b(?:acontece|ser[aá] realizado|edi[cç][aã]o|"
    r"re[uú]ne|inscri[cç][oõ]es|debate|especialistas|palestr|participantes)\b|"
    r"\binscri[cç][oõ]es abertas\b|"
    r"\bre[uú]ne\b.{0,70}\b(?:setor|representantes|especialistas|empres[aá]rios)\b",
    re.I,
)
IMPACT_OVERRIDES_EVENT = re.compile(
    r"aprova|promulga|regulamenta|lei |tribut|\bselic\b|"
    r"\bipca\b|\bdata de entrega\b|\bregras?\b|"
    r"\bfinanciamento\b|\bdecis[aã]o\b|\bresultado\b",re.I,
)

# Avisos operacionais de poucas horas/dias não podem sobreviver à sua validade.
# Não aplica automaticamente a mudanças permanentes ("a partir de", "nova regra").
EPHEMERAL_ADVISORY = re.compile(
    r"\b(?:rod[ií]zio|interdi[cç][aã]o|bloqueio(?:s)? de (?:via|rua|tr[aâ]nsito)|"
    r"suspens[aã]o (?:tempor[aá]ria )?(?:de|do|da)|alerta de (?:chuva|temporal)|"
    r"esta[cç][aã]o(?:es)? fechad[ao]s?|linhas? paralisad[ao]s?)\b",
    re.I,
)
PERMANENT_CHANGE = re.compile(
    r"\b(?:a partir de|permanente|definitiv[oa]|novas? regras?|nova legisla[cç][aã]o|"
    r"mudan[cç]as? permanente|passar[aá] a valer)\b", re.I,
)
WEEKDAYS = {"segunda":0,"terca":1,"terça":1,"quarta":2,"quinta":3,
            "sexta":4,"sabado":5,"sábado":5,"domingo":6}
WEEKDAY_RE = re.compile(r"\b(?:nesta|na|hoje,?\s*)\s*(segunda|ter[cç]a|quarta|quinta|sexta|s[aá]bado|domingo)(?:-feira)?\b", re.I)
NUMERIC_DAY_RE = re.compile(r"\b(?:dia\s+)?\(?([0-3]?\d)\)?\s*(?:de\s+)?(?:outubro|novembro|dezembro|janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|setembro)\b|\(([0-3]?\d)\)", re.I)
MONTH_NAMES = {'janeiro':1,'fevereiro':2,'março':3,'marco':3,'abril':4,'maio':5,'junho':6,
               'julho':7,'agosto':8,'setembro':9,'outubro':10,'novembro':11,'dezembro':12}

def expire_date_of_notice(title, published_local):
    """Devolve data local de término quando título informa prazo reconhecível.

    Sem data ou horário identificável, NÃO presumir expiração.
    """
    s=title.lower()
    m=NUMERIC_DAY_RE.search(s)
    if m:
        day=int(m.group(1) or m.group(2))
        month_match=re.search(r"\b(janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\b",m.group(0))
        month=MONTH_NAMES.get(month_match.group(1), published_local.month) if month_match else published_local.month
        try:return published_local.date().replace(day=day, month=month)
        except ValueError:return None
    if re.search(r"\b(?:amanh[aã])\b",s):return published_local.date()+timedelta(days=1)
    if re.search(r"\b(?:hoje|nesta tarde|nesta noite|nesta manh[aã]|na tarde e noite)\b",s):
        # O dia da semana por extenso, se houver, é mais forte do que 'nesta'.
        weekday=WEEKDAY_RE.search(s)
        if not weekday:return published_local.date()
    weekday=WEEKDAY_RE.search(s)
    if weekday:
        token=weekday.group(1).lower()
        target=WEEKDAYS.get(token)
        if target is None:return None
        # 'nesta quarta-feira': próximo mesmo dia na semana de publicação,
        # conservador se o aviso vier de um feed atrasado.
        delta=(target-published_local.weekday())%7
        return published_local.date()+timedelta(days=delta)
    return None

def is_expired_notice(item, cutoff):
    title=item.get('title','')
    if not EPHEMERAL_ADVISORY.search(title) or PERMANENT_CHANGE.search(title):return False
    try:published=datetime.fromisoformat(item['publishedAt']).astimezone(TZ)
    except (KeyError,ValueError,TypeError):return False
    ends=expire_date_of_notice(title,published)
    return bool(ends and ends < cutoff.astimezone(TZ).date())

def rejection_reason(item, cutoff=None):
    """Filtra com motivo auditável; nenhuma chamada de rede ou IA."""
    title=item['title']
    if BLOCKED_TOPICS.search(title):return 'assunto_fora_do_perfil'
    if PROMOTIONAL.search(title):return 'publicidade_ou_promocao'
    if LOW_IMPACT_CURIOSITY.search(title):return 'curiosidade_de_baixo_impacto'
    if EVENT_ANNOUNCEMENT.search(title) and not IMPACT_OVERRIDES_EVENT.search(title):
        return 'convite_ou_evento_sem_noticia'
    if item.get('feed','').endswith('— Esportes'):return 'esporte_nao_prioritario'
    feed=item.get('feed','').lower()
    if any(f in feed for f in ('forbes','harper','hotelier')):
        if interest_topic(item)!='Mercado de luxo':return 'veiculo_geral_sem_assunto_de_luxo'
    if 'diário do transporte' in feed and not is_city_story(title):return 'fora_da_capital_sp'
    if 'metrópoles — são paulo' in feed and not is_city_story(title):return 'fora_da_capital_sp'
    if feed==METRO_OFFICIAL and not is_capital_news(item):return 'fora_da_capital_sp'
    if SECTOR_FEED.search(feed) and not is_sector_story(item):
        return 'sem_conteudo_imobiliario'
    if ('agência mural' in feed or 'jornal da usp' in feed) and item.get('baseCategory')=='São Paulo':
        if not (is_city_story(title) or ECONOMY_TOPICS.search(title) or PUBLIC_IMPACT_TOPICS.search(title)):
            return 'local_sem_impacto_evidente'
    if cutoff is not None and is_expired_notice(item,cutoff):return 'aviso_ja_vencido'
    return None

def is_relevant(item, cutoff=None):
    return rejection_reason(item, cutoff) is None

def relevance_score(item, cutoff):
    title=item["title"]
    category=item["category"]
    # Nota principal por pertinência; idade tem efeito moderado dentro das 48h.
    score={"Mercado imobiliário": 7, "São Paulo": 5,
           "Mundo": 3, "Brasil": 2, "Interesses": 2}.get(category,0)
    if ECONOMY_TOPICS.search(title): score+=9
    if PUBLIC_IMPACT_TOPICS.search(title): score+=8
    if GLOBAL_IMPACT_TOPICS.search(title): score+=6
    if LOCAL_CONTEXT_TOPICS.search(title): score+=5
    if LOCAL_CHANGE_TOPICS.search(title) and category=="São Paulo": score+=3
    if SECTOR_CONTEXT_TOPICS.search(title): score+=8
    elif category=="Mercado imobiliário" and re.search(PATTERNS["Mercado imobiliário"],title,re.I): score+=5
    if F1_TOPICS.search(title): score+=11
    # Notícia sobre obra/regulação/número tem prioridade sobre evento corporativo.
    if EVENT_ANNOUNCEMENT.search(title): score-=14
    if PROMOTIONAL.search(title) or LOW_IMPACT_CURIOSITY.search(title): score-=25
    if category=="Interesses" and interest_topic(item): score+=13
    # Manchetes de fonte econômica especializada podem ser importantes mesmo
    # sem trazer a palavra 'economia' explicitamente.
    if item.get("feed","").endswith("— Economia") and category=="Brasil": score+=2
    if item.get("source")=="IBGE" and category=="Brasil": score+=2
    if category=="São Paulo" and is_city_story(title): score+=7
    if category=="Mercado imobiliário" and SECTOR_FEED.search(item.get('feed','')):score+=6
    if category=="Mercado imobiliário" and is_sector_story(item):score+=5
    hours=max(0,(cutoff-datetime.fromisoformat(item["publishedAt"])).total_seconds()/3600)
    score-=min(hours/16,2.5)
    return score


def select(items, now):
    local=now.astimezone(TZ)
    edition_date=local.date()
    cutoff=min(datetime.combine(edition_date,time(7,30),TZ).astimezone(timezone.utc),
               now.astimezone(timezone.utc))
    start=cutoff-timedelta(hours=48)
    # Só metadados com datas válidas dentro da janela editorial.
    candidates=[]; seen_ids=set(); seen_titles=set()
    for entry in items:
        try: when=datetime.fromisoformat(entry['publishedAt'])
        except (ValueError,KeyError): continue
        if when.tzinfo is None: continue
        if not (start <= when <= cutoff): continue
        if not is_relevant(entry,cutoff): continue
        normalized=re.sub(r'[^a-z0-9]+','',unicodedata.normalize('NFKD',entry['title']).encode('ascii','ignore').decode().lower())
        signature=normalized[:100]
        if entry['id'] in seen_ids or signature in seen_titles: continue
        seen_ids.add(entry['id']);seen_titles.add(signature)
        article={k:v for k,v in entry.items() if k!='baseCategory'}
        article['category']=classify(entry)
        article['topic']=interest_topic(entry) if article['category']=='Interesses' else None
        if article['category']=='Interesses' and not article['topic']: continue
        article['contentType']='noticia' # Não apresentar artigos velhos como notícias do dia.
        article['_score']=relevance_score(article,cutoff)
        candidates.append(article)
    candidates.sort(key=lambda x:(x['_score'],x['publishedAt']),reverse=True)
    min_score={'Mundo':8.5,'Brasil':9,'São Paulo':9,'Mercado imobiliário':12,'Interesses':9}
    selected=[]; used=set(); source_count={}; topic_count={}
    # Primeira passagem nos interesses: mostrar assuntos DIFERENTES.
    for category, target in TARGETS:
        picked=0
        category_candidates=[a for a in candidates if a['category']==category and a['_score']>=min_score[category]]
        for pass_number in (0,1) if category in ('Interesses','Mundo','Brasil','São Paulo') else (1,):
            for article in category_candidates:
                if picked >= target:break
                aid=article['id'];src=article['source'];topic=article['topic']
                if aid in used or source_count.get(src,0)>=2: continue
                if category=='Interesses':
                    if pass_number==0 and topic_count.get(topic,0)>0: continue
                    if pass_number==1 and topic_count.get(topic,0)>=2: continue
                if category in ('Mundo','Brasil','São Paulo') and pass_number==0:
                    if any(x['category']==category and x['source']==src for x in selected):
                        continue
                selected.append(article);used.add(aid);picked+=1
                source_count[src]=source_count.get(src,0)+1
                if topic: topic_count[topic]=topic_count.get(topic,0)+1
            if picked>=target:break
    selected.sort(key=lambda x:(x['_score'],x['publishedAt']),reverse=True)
    for article in selected:article.pop('_score',None)
    return selected,edition_date.isoformat()

def fetch(url):
    req=Request(url,headers={"User-Agent":"OrbitaPilot/0.7.3-preview (+RSS reader, personal testing)","Accept":"application/json, application/rss+xml, application/atom+xml, application/xml, text/xml", "Accept-Encoding":"identity"})
    with urlopen(req,timeout=13) as response:
        data=response.read(1_200_001)
        if len(data)>1_200_000:raise ValueError("Feed excede limite de segurança")
        return normalize_response_bytes(data)

def build(now=None,fixture=None,out=OUT):
    now=now or datetime.now(timezone.utc)
    stories=[]; warnings=[]; ok=0
    feeds_ok=set()
    feed_warnings={}
    for name,cat,url in FEEDS:
        try:
            raw=Path(fixture).read_bytes() if fixture else fetch(url)
            articles=parse_rss(raw,name,cat)
            if not articles: raise ValueError("Feed vazio, sem datas ou em formato inesperado")
            stories.extend(articles)
            ok+=1
            feeds_ok.add(name)
            print(f"[FEED OK] {name}: {len(articles)} entradas", flush=True)
        except Exception as exc:
            message=f"{name}: {type(exc).__name__} ({str(exc)[:110]})"
            warnings.append(message)
            feed_warnings[name]=message
            print(f"[FEED FALHOU] {message}",file=sys.stderr,flush=True)
    for name,cat,url in (API_SOURCES if not fixture else []):
        try:
            raw=Path(fixture).read_bytes() if fixture else fetch(url)
            articles=parse_ibge_news(raw,name,cat)
            if not articles: raise ValueError("API vazia ou formato inesperado")
            stories.extend(articles)
            ok+=1
            feeds_ok.add(name)
            print(f"[API OK] {name}: {len(articles)} entradas",flush=True)
        except Exception as exc:
            message=f"{name}: {type(exc).__name__} ({str(exc)[:110]})"
            warnings.append(message)
            feed_warnings[name]=message
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
            if is_relevant(item,editorial_cutoff): recent_unblocked+=1
    blocked_reasons={}
    for entry in stories:
        when=datetime.fromisoformat(entry['publishedAt'])
        if not editorial_cutoff-timedelta(hours=48)<=when<=editorial_cutoff:continue
        reason=rejection_reason(entry,editorial_cutoff)
        if reason:blocked_reasons[reason]=blocked_reasons.get(reason,0)+1
    chosen,day=select(stories,now)
    coverage=[{"category":category,"target":n,"count":sum(a["category"]==category for a in chosen)} for category,n in TARGETS]
    cutoff_sp=editorial_cutoff.astimezone(TZ).strftime('%d/%m/%Y %H:%M')
    print(f"[DIAGNÓSTICO] Fuso SP; corte editorial {cutoff_sp}; feeds OK {ok}/{len(FEEDS)+len(API_SOURCES)}; "
          f"entradas totais {len(stories)}; últimas 48h antes do corte {seen_recent}; "
          f"sem bloqueios temáticos {recent_unblocked}; selecionadas {len(chosen)}", flush=True)
    print("[EDITORIAS] "+", ".join(f"{x['category']}={x['count']}" for x in coverage),flush=True)
    # Diagnóstico por editoria ANTES do limiar, para separar falta de notícias
    # de seleção editorial rigorosa. Não publica conteúdo extra.
    candidates={category:0 for category,_ in TARGETS}
    qualified={category:0 for category,_ in TARGETS}
    for entry in stories:
        when=datetime.fromisoformat(entry["publishedAt"])
        if not editorial_cutoff-timedelta(hours=48)<=when<=editorial_cutoff or not is_relevant(entry,editorial_cutoff):
            continue
        cat=classify(entry)
        candidates[cat]+=1
        trial={**entry,"category":cat}
        if relevance_score(trial,editorial_cutoff)>={"Mundo":8.5,"Brasil":9,"São Paulo":9,"Mercado imobiliário":12,"Interesses":9}[cat]:
            qualified[cat]+=1
    print("[CANDIDATOS] "+", ".join(f"{cat}: {candidates[cat]} recentes, {qualified[cat]} com pontuação suficiente" for cat,_ in TARGETS), flush=True)
    # Diagnóstico completo incluso para fontes que responderam mas não trouxeram
    # notícias da capital. Somente contagens; nenhum texto protegido é copiado.
    feed_diagnostics=[]
    for name,base,url in FEEDS+API_SOURCES:
        src_items=[item for item in stories if item.get('feed')==name]
        in_window=[item for item in src_items if
            editorial_cutoff-timedelta(hours=48)<=datetime.fromisoformat(item['publishedAt'])<=editorial_cutoff]
        eligible=[item for item in in_window if is_relevant(item,editorial_cutoff)]
        city=[item for item in eligible if classify(item)=='São Paulo']
        luxury=[item for item in eligible if classify(item)=='Interesses' and interest_topic(item)=='Mercado de luxo']
        feed_diagnostics.append({
            'feed':name,'status':'ok' if name in feeds_ok else 'error',
            'parsed':len(src_items),'recent':len(in_window),
            'eligible':len(eligible),'cityEligible':len(city),
            'luxuryEligible':len(luxury),
            'error':feed_warnings.get(name),
        })
    # Não declarar 'fonte validada' apenas porque o servidor respondeu.
    # Acesso gratuito ao artigo e licença são verificações à parte.
    # Retenção de exemplos apenas de manchete, fonte e motivo (sem corpos RSS).
    # Permite ver o que faltou nas editorias, sem publicar notícias rejeitadas.
    editorial_samples=[]
    for item in stories:
        if not SECTOR_FEED.search(item.get('feed','')):continue
        when=datetime.fromisoformat(item['publishedAt'])
        if not editorial_cutoff-timedelta(hours=48)<=when<=editorial_cutoff:continue
        reason=rejection_reason(item,editorial_cutoff)
        if len([x for x in editorial_samples if x['feed']==item['feed']])>=4:continue
        editorial_samples.append({'feed':item['feed'],'title':item['title'],
                                  'classification':classify(item),
                                  'rejection':reason or 'elegivel'})
    # Estudos e indicadores de 3 a 14 dias são candidatos a uma seção FUTURA,
    # nunca misturados nas manchetes de 48h da edição diária.
    trend_keywords=re.compile(
        r"pesquisa|levantamento|[ií]ndice|indicador|dados? de|\bpre[cç]os?\b|"
        r"\bvendas?\b|\blan[cç]amentos?\b|financiament|cr[eé]dito imobili|\bestoque\b",re.I)
    trend_candidates=[]
    seen_trend=set()
    for item in sorted(stories,key=lambda e:e['publishedAt'],reverse=True):
        when=datetime.fromisoformat(item['publishedAt'])
        age=editorial_cutoff-when
        if not timedelta(hours=48)<age<=timedelta(days=14):continue
        if not is_sector_story(item) or not trend_keywords.search(item['title']):continue
        if rejection_reason(item,editorial_cutoff) or item['id'] in seen_trend:continue
        seen_trend.add(item['id'])
        trend_candidates.append({k:item[k] for k in ('title','url','source','feed','publishedAt')})
        if len(trend_candidates)>=6:break
    data={"newCandidateFeeds":["Metrópoles — São Paulo","Metrô de São Paulo — Notícias","SindusCon-SP — Imobiliário"],"previewVersion":"0.7.3","editionDate":day,"timezone":"America/Sao_Paulo","generatedAt":now.isoformat(),"status":"ready" if chosen else "unavailable","sourceFeedsOk":ok,"sourceFeedsTotal":len(FEEDS)+len(API_SOURCES),"items":chosen,"coverage":coverage,"feedDiagnostics":feed_diagnostics,
          "sectorEditorialSamples":editorial_samples,
          "trendCandidatesForReviewOnly":trend_candidates,"editorialDiagnostics":{"blockedByReason":blocked_reasons,"cityUniqueSources":len({a['source'] for a in chosen if a['category']=='São Paulo'}),"selectionUsesTitleOnly":True,"trendCandidatesAreNotPublished":True},"warnings":warnings,"editorialNote":"Prévia 0.7.3 (NÃO publicar): piloto experimental: manchetes, URLs e datas de RSS e API pública, com filtro de relevância por regras. Sem resumos IA ou checagem editorial humana. Acesso público não implica autorização para redistribuição comercial; licenças precisam ser validadas."}
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

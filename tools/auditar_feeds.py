#!/usr/bin/env python3
"""Órbita 0.6: auditoria focada em SÃO PAULO (capital) e LUXO.

Executar em GitHub Actions com Python 3, somente biblioteca padrão.
NÃO publica no app; não grava matérias/imagens; não faz login, bypass de paywall
ou acesso a recursos pagos. Só testa metadados de feeds e páginas públicas.
Saídas compatíveis com workflow já instalado:
    auditoria_feeds.csv
    auditoria_feeds.json
"""
from __future__ import annotations

import csv
import gzip
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError

# Tipos: RSS = tentar analisar feed; PAGINA = somente verificar resposta da página.
# A classificação é hipótese de cobertura, NÃO prova notícias da capital/luxo.
# Apenas 'Mobilize', Secovi etc. têm URL ou RSS documentado no próprio site;
# outros endereços RSS abaixo são CANDIDATOS e podem retornar erro/stale.
SOURCES = [
    # São Paulo — capital (sinal geográfico será analisado título a título)
    {"fonte":"Mobilize — notícias (RSS oficial)", "editoria":"São Paulo", "modo":"RSS", "url":"https://www.mobilize.org.br/rss/noticias/", "situacao":"RSS oficial; filtrar SP capital"},
    {"fonte":"Mobilize — metrô e trem (RSS oficial)", "editoria":"São Paulo", "modo":"RSS", "url":"https://www.mobilize.org.br/rss/noticias/?c=14", "situacao":"RSS oficial; alcance nacional"},
    {"fonte":"Agência SP — Notícias", "editoria":"São Paulo", "modo":"RSS", "url":"https://www.agenciasp.sp.gov.br/feed/", "situacao":"RSS candidato; erro HTTP 500 na auditoria anterior"},
    {"fonte":"Sebrae-SP — Notícias", "editoria":"São Paulo", "modo":"RSS", "url":"https://sp.agenciasebrae.com.br/feed/", "situacao":"RSS antes funcional; cobre o estado"},
    {"fonte":"Diário do Transporte — candidato", "editoria":"São Paulo", "modo":"RSS", "url":"https://diariodotransporte.com.br/feed/", "situacao":"RSS candidato a verificar"},
    {"fonte":"Prefeitura de São Paulo — Notícias", "editoria":"São Paulo", "modo":"PAGINA", "url":"https://prefeitura.sp.gov.br/noticias", "situacao":"Site oficial; sem RSS homologado"},
    {"fonte":"VEJA São Paulo — portal", "editoria":"São Paulo", "modo":"PAGINA", "url":"https://vejasp.abril.com.br/", "situacao":"Artigos gratuitos e exclusivos; checar paywall"},
    # Mercado de luxo — alguns portais generalistas precisam de filtragem
    {"fonte":"Forbes Brasil — Geral", "editoria":"Mercado de luxo", "modo":"RSS", "url":"https://forbes.com.br/feed/", "situacao":"RSS antes funcional; mistura assuntos"},
    {"fonte":"Hotelier News — Hotelaria", "editoria":"Mercado de luxo", "modo":"RSS", "url":"https://hoteliernews.com.br/feed/", "situacao":"Endereço RSS identificado; filtrar hotelaria premium"},
    {"fonte":"Mercado & Consumo — Varejo", "editoria":"Mercado de luxo", "modo":"RSS", "url":"https://mercadoeconsumo.com.br/feed/", "situacao":"Endereço RSS; última data pode estar antiga"},
    {"fonte":"Harper's Bazaar Brasil — candidato", "editoria":"Mercado de luxo", "modo":"RSS", "url":"https://harpersbazaar.uol.com.br/feed/", "situacao":"RSS candidato; validar endpoint"},
    {"fonte":"Robb Report Brasil — feed candidato", "editoria":"Mercado de luxo", "modo":"RSS", "url":"https://www.robbreport.com.br/feed/", "situacao":"RSS NÃO confirmado; portal existe"},
    {"fonte":"Robb Report Brasil — portal", "editoria":"Mercado de luxo", "modo":"PAGINA", "url":"https://www.robbreport.com.br/", "situacao":"Portal aberto; não comprova feed"},
    {"fonte":"Casa Vogue — portal", "editoria":"Mercado de luxo", "modo":"PAGINA", "url":"https://casavogue.globo.com/", "situacao":"Site; arquitetura/design e acesso variáveis"},
    {"fonte":"GQ Brasil — portal", "editoria":"Mercado de luxo", "modo":"PAGINA", "url":"https://gq.globo.com/", "situacao":"Site; estilo e consumo, RSS não confirmado"},
]

ATOM = '{http://www.w3.org/2005/Atom}'
DC = '{http://purl.org/dc/elements/1.1/}'

# Sinais de cidade são apenas possíveis correspondências. 'São Paulo' pode
# significar estado, município, time ou pessoa: confirmar geografia depois.
CAPITAL_RE = re.compile(r'\b(?:s[aã]o paulo|paulistan[oa]s?|capital paulista|prefeitura de sp|metro de sp|metr[oô] de sp|linha\s*[12679][\s-]|faria lima|itaim bibi|pinheiros|moema|brooklin|jardins|vila mariana|ibirapuera|bela vista|jardim europa|vila madalena|avenida paulista|marginal tiet[eê]|marginal pinheiros|campo belo|para[ií]so|augusta|oscar freire|cptm)\b', re.I)
LUXURY_RE = re.compile(r'\b(?:luxo|luxury|premium|alto padr[aã]o|exclusiv[oa]s?|sofistica(?:do|da)|joalheria|relojoaria|rolex|patek|audemars|cartier|herm[eè]s|louis vuitton|chanel|dior|prada|gucci|ferrari|porsche|lamborghini|bentley|rolls[- ]royce|private jet|jato executivo|iate|yacht|hotel de luxo|hotel cinco estrelas|five stars|four seasons|fasano|rosewood|mandarin oriental|relais ch[aâ]teaux|alta gastronomia|michelin|mans[aã]o)\b', re.I)


def parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value.strip())
    except (ValueError, IndexError, TypeError):
        try:
            dt = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_first(element: ET.Element, keys: tuple[str, ...]) -> str:
    for key in keys:
        text = element.findtext(key)
        if text and text.strip():
            return text.strip()
    return ''


def parse_xml(blob: bytes) -> list[tuple[str, datetime | None]]:
    root = ET.fromstring(blob)
    name = root.tag.rsplit('}', 1)[-1].lower()
    if name not in ('rss', 'rdf', 'feed'):
        raise ValueError(f'XML não é RSS/Atom (raiz={name})')
    entries = root.findall('.//' + ATOM + 'entry') if name == 'feed' else root.findall('.//item')
    if name == 'rdf' and not entries:
        entries = root.findall('.//{http://purl.org/rss/1.0/}item')
    results = []
    for entry in entries:
        if name == 'feed':
            title = get_first(entry, (ATOM + 'title', 'title'))
            raw_date = get_first(entry, (ATOM + 'published', ATOM + 'updated'))
        else:
            title = get_first(entry, ('title','{http://purl.org/rss/1.0/}title'))
            raw_date = get_first(entry, ('pubDate', DC + 'date', 'date', '{http://purl.org/rss/1.0/modules/content/}date'))
        title = re.sub(r'\s+', ' ', html.unescape(title)).strip()[:160]
        results.append((title, parse_date(raw_date)))
    return results


class PageTitle(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title = ''

    def handle_starttag(self, tag, attrs):
        if tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

    def handle_data(self, text):
        if self.in_title:
            self.title += text


def inspect(source: dict[str, str], now: datetime) -> dict:
    record = {
        'fonte': source['fonte'],
        'categoria': source['editoria'],
        'modo': source['modo'],
        'url': source['url'],
        'situacao': source['situacao'],
        'status': 'ERRO',
        'http': '', 'tipo': '', 'itens': 0,
        'datas_validas': 0, 'ultimas_48h': 0, 'ultimos_7dias': 0,
        'possivel_sp_capital_7d': 0, 'possivel_luxo_7d': 0,
        'data_mais_recente': '', 'exemplo': '', 'exemplo_relevante': '',
        'erro': '', 'licenca': 'NÃO VERIFICADA', 'paywall': 'NÃO VERIFICADO',
    }
    headers = {
        'User-Agent':'OrbitaSourceAudit/0.6 (pilot; public metadata and links only)',
        'Accept':'application/rss+xml,application/atom+xml,application/xml,text/xml,text/html;q=0.8,*/*;q=0.5',
        'Accept-Encoding':'gzip',
    }
    req = urllib.request.Request(source['url'], headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            record['http'] = getattr(response, 'status', 200)
            record['tipo'] = response.headers.get('Content-Type', '')[:120]
            content = response.read(4_000_000)
            enc = response.headers.get('Content-Encoding', '').lower()
            if 'gzip' in enc or content[:2] == b'\x1f\x8b':
                content = gzip.decompress(content)
        if source['modo'] == 'PAGINA':
            title_parser = PageTitle()
            title_parser.feed(content[:250_000].decode('utf-8', 'replace'))
            record['exemplo'] = re.sub(r'\s+', ' ', title_parser.title).strip()[:160]
            record['status'] = 'PAGINA_OK' if b'<html' in content[:4000].lower() else 'PAGINA_INDEFINIDA'
        else:
            feed_entries = parse_xml(content)
            times = [dt for title, dt in feed_entries if dt]
            recent = [(title, dt) for title,dt in feed_entries if dt and now-timedelta(days=7) <= dt <= now+timedelta(minutes=20)]
            record['itens'] = len(feed_entries)
            record['datas_validas'] = len(times)
            record['ultimas_48h'] = sum(now - timedelta(hours=48) <= d <= now + timedelta(minutes=20) for d in times)
            record['ultimos_7dias'] = len(recent)
            record['possivel_sp_capital_7d'] = sum(bool(CAPITAL_RE.search(title)) for title, _ in recent)
            record['possivel_luxo_7d'] = sum(bool(LUXURY_RE.search(title)) for title, _ in recent)
            record['data_mais_recente'] = max(times).isoformat() if times else ''
            record['exemplo'] = next((t for t,d in feed_entries if t), '')
            matcher = CAPITAL_RE if source['editoria'] == 'São Paulo' else LUXURY_RE
            record['exemplo_relevante'] = next((t for t,d in recent if matcher.search(t)), '')
            record['status'] = 'OK' if len(feed_entries) > 0 else 'VAZIO'
    except Exception as exc:
        record['erro'] = (type(exc).__name__ + ': ' + str(exc))[:260]
    return record


def main() -> int:
    now = datetime.now(timezone.utc)
    rows=[]
    for source in SOURCES:
        result=inspect(source, now)
        rows.append(result)
        print(f"[{result['status']:<17}] {result['fonte'][:40]:<40} "
              f"itens={result['itens']:<4} 48h={result['ultimas_48h']:<3} "
              f"sinaisSP={result['possivel_sp_capital_7d']:<2} "
              f"sinaisLuxo={result['possivel_luxo_7d']:<2} "
              f"{result['erro'] or result['data_mais_recente']}", flush=True)
    with open('auditoria_feeds.csv','w',encoding='utf-8-sig',newline='') as fp:
        writer=csv.DictWriter(fp, fieldnames=list(rows[0]), delimiter=';')
        writer.writeheader(); writer.writerows(rows)
    Path('auditoria_feeds.json').write_text(json.dumps({
        'executado_em_utc': now.isoformat(),
        'nota':'Sinais de tema no título não confirmam cidade, luxo, artigos gratuitos ou licença comercial. PÁGINA_OK não é feed.',
        'resultados':rows,
    },ensure_ascii=False,indent=2),encoding='utf-8')
    feed_ok=sum(r['status']=='OK' for r in rows)
    page_ok=sum(r['status']=='PAGINA_OK' for r in rows)
    print(f"RESUMO: {feed_ok} RSS funcionando; {page_ok} páginas acessíveis; "
          f"{sum(r['ultimas_48h'] for r in rows)} entradas RSS em 48h (antes de deduplicar).", flush=True)
    print('ATENÇÃO: esta auditoria não verifica paywall, direitos de publicação nem acesso a conteúdo completo.', flush=True)
    return 0  # Sempre enviar os relatórios mesmo com alguns sites inacessíveis.

if __name__ == '__main__':
    sys.exit(main())

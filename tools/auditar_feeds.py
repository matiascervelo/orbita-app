#!/usr/bin/env python3
"""Auditoria somente de metadados RSS/Atom. Não redistribui matérias nem fotos.

Uso: python3 tools/auditar_feeds.py
Saída: auditoria_feeds.csv / auditoria_feeds.json
Requer somente a biblioteca padrão. Rodar no GitHub Actions para acesso externo.
"""
from __future__ import annotations

import csv
import gzip
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

# Etapa 2: conserva as dez fontes testadas e adiciona sete candidatas.
# 'Confirmado' = URL identificada em página oficial ou funcionando em teste anterior;
# NÃO significa licença de uso comercial nem ausência de paywall.
FEEDS = [
    ("Agência Brasil — Internacional", "Mundo", "https://agenciabrasil.ebc.com.br/rss/internacional/feed.xml"),
    ("Agência Brasil — Política", "Brasil", "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml"),
    ("Agência Brasil — Economia", "Economia", "https://agenciabrasil.ebc.com.br/rss/economia/feed.xml"),
    ("InfoMoney", "Economia", "https://www.infomoney.com.br/feed/"),
    ("Secovi-SP", "Imobiliário", "https://secovi.com.br/feed/"),
    ("CBIC", "Imobiliário", "https://cbic.org.br/feed/"),
    ("G1 — Mundo", "Mundo", "https://g1.globo.com/rss/g1/mundo/"),
    ("G1 — Política", "Brasil", "https://g1.globo.com/rss/g1/politica/"),
    ("CNN Brasil", "Brasil", "https://admin.cnnbrasil.com.br/feed/"),
    ("Melhores Destinos", "Viagens", "https://www.melhoresdestinos.com.br/feed/"),
    # Complementos a validar na auditoria real (sem republicar conteúdo):
    ("Agência SP — Notícias", "São Paulo", "https://www.agenciasp.sp.gov.br/feed/"),
    ("Sebrae-SP — Notícias", "Economia", "https://sp.agenciasebrae.com.br/feed/"),
    ("ArchDaily Brasil", "Arquitetura e design", "https://feeds.feedburner.com/ArchdailyBR"),
    ("Forbes Brasil", "Mercado de luxo", "https://forbes.com.br/feed/"),
    ("Motorsport Brasil — Fórmula 1", "Fórmula 1", "https://motorsport.uol.com.br/rss/f1/news/"),
    # Candidatos ainda NÃO verificados como RSS: falhas são esperadas e informativas.
    ("CNN Viagem & Gastronomia — candidato", "Gastronomia e viagens", "https://www.cnnbrasil.com.br/viagemegastronomia/feed/"),
    ("Prazeres da Mesa — candidato", "Gastronomia e viagens", "https://www.prazeresdamesa.com.br/feed/"),
]
NS = {"atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/"}

def parse_date(s: str) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        dt = parsedate_to_datetime(s)
    except (ValueError, TypeError, IndexError):
        try:
            dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_xml(blob: bytes):
    root = ET.fromstring(blob)
    tag = root.tag.rsplit('}', 1)[-1].lower()
    if tag not in ('rss','feed','rdf'):
        raise ValueError(f'XML sem estrutura RSS/Atom reconhecível: {tag}')
    if tag == 'feed':
        items = root.findall('atom:entry', NS)
        if not items:
            items = root.findall('{http://www.w3.org/2005/Atom}entry')
        title_tag='atom:title'; date_tags=('atom:published','atom:updated')
    else:
        items = root.findall('.//item')
        title_tag='title'; date_tags=('pubDate','dc:date','date')
    rec=[]
    for item in items:
        title = item.findtext(title_tag, default='', namespaces=NS).strip()
        if not title and tag == 'feed':
            title=item.findtext('{http://www.w3.org/2005/Atom}title',default='').strip()
        dt=None
        for dt_tag in date_tags:
            dt=parse_date(item.findtext(dt_tag, default='', namespaces=NS))
            if dt: break
        rec.append((re.sub(r'\s+',' ',title)[:140],dt))
    return rec


def inspect(name: str, categoria: str, url: str, now: datetime):
    out = dict(fonte=name,categoria=categoria,url=url,status='ERRO',http='',tipo='',itens=0,
               datas_validas=0,ultimas_48h=0,ultimos_7dias=0,data_mais_recente='',exemplo='',erro='')
    req = urllib.request.Request(url,headers={
        'User-Agent': 'OrbitaPilotSourceAudit/0.6 (RSS metadata only; contact owner for content licensing)',
        'Accept':'application/rss+xml, application/atom+xml, application/xml, text/xml, */*',
        'Accept-Encoding': 'gzip',
    })
    try:
        with urllib.request.urlopen(req, timeout=14) as res:
            out['http']=res.status
            out['tipo']=res.headers.get('Content-Type','')[:120]
            content=res.read(3_000_000)
            if res.headers.get('Content-Encoding','').lower() == 'gzip' or content[:2]==b'\x1f\x8b':
                content=gzip.decompress(content)
        items=parse_xml(content)
        times=[t for _,t in items if t is not None]
        out['itens']=len(items)
        out['datas_validas']=len(times)
        out['ultimas_48h']=sum(now-timedelta(hours=48)<=t<=now+timedelta(minutes=20) for t in times)
        out['ultimos_7dias']=sum(now-timedelta(days=7)<=t<=now+timedelta(minutes=20) for t in times)
        out['data_mais_recente']=max(times).isoformat() if times else ''
        out['exemplo']=next((title for title,_ in items if title),'')
        out['status']='OK' if items else 'VAZIO'
    except Exception as exc:
        out['erro']=f'{type(exc).__name__}: {str(exc)[:250]}'
    return out


def main():
    now=datetime.now(timezone.utc)
    results=[]
    for name,cat,url in FEEDS:
        item=inspect(name,cat,url,now)
        results.append(item)
        print(f"{item['status']:>5} | {item['fonte']:<31} | itens={item['itens']:<4} 48h={item['ultimas_48h']:<3} | {item['erro'] or item['data_mais_recente']}",flush=True)
    keys=list(results[0])
    with open('auditoria_feeds.csv','w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=keys,delimiter=';')
        writer.writeheader(); writer.writerows(results)
    Path('auditoria_feeds.json').write_text(json.dumps({'executado_em_utc':now.isoformat(),'resultados':results},ensure_ascii=False,indent=2),encoding='utf-8')
    success=sum(x['status']=='OK' for x in results)
    recent=sum(x['ultimas_48h'] for x in results)
    print(f'RESUMO: {success}/{len(results)} feeds responderam com itens; {recent} entradas com datas nas últimas 48h (ainda podem existir duplicatas).')
    print('AVISO: OK significa feed legível, NÃO valida licença comercial nem artigo sem paywall.')
    # Volta exit 0 para sempre carregar os relatórios, mesmo se as fontes falharem.
    return 0

if __name__ == '__main__':
    sys.exit(main())

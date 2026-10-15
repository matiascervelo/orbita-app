"""Testes locais isolados da prévia: nenhum acesso à internet."""
import json
import sys
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import coletor_07 as app
NOW=datetime(2026,10,13,13,0,tzinfo=timezone.utc)

def article(id,title,feed='Agência Brasil — Política',base='Brasil',hr=10,day='2026-10-13'):
    return {'id':id,'title':title,'url':'https://example.org/'+id,
            'publishedAt':f'{day}T{hr:02d}:00:00+00:00',
            'source':feed.split(' — ')[0], 'feed':feed, 'baseCategory':base}

class Orbita07Tests(unittest.TestCase):
    def test_source_list_is_based_on_audited_rss(self):
        self.assertEqual(len(app.FEEDS),18)
        self.assertEqual(len({url for _,_,url in app.FEEDS}),len(app.FEEDS))
        self.assertTrue(all('agenciasp' not in url for _,_,url in app.FEEDS))
        self.assertTrue(all('mobilize' not in url for _,_,url in app.FEEDS))
        self.assertEqual(sum(count for _,count in app.TARGETS),14)

    def test_specialist_topics_always_classified(self):
        cases=[
          ('Arquiteto cria novo museu no litoral','ArchDaily Brasil — Arquitetura','Arquitetura e design'),
          ('Equipe apresenta novos pneus para GP','Motorsport Brasil — Fórmula 1','Fórmula 1'),
          ('Festival reúne chefs na cidade','Prazeres da Mesa — Gastronomia','Gastronomia'),
          ('Companhias anunciam novas rotas','Melhores Destinos — Viagens','Viagens'),
          ('Rolex anuncia nova coleção de relógios','Forbes Brasil — Geral','Mercado de luxo'),
        ]
        for i,(title,feed,topic) in enumerate(cases):
            item=article(str(i),title,feed,'Interesses')
            self.assertEqual(app.classify(item),'Interesses')
            self.assertEqual(app.interest_topic(item),topic)

    def test_luxury_only_when_evidence_in_title(self):
        generic=article('pol','Senadores debatem reforma eleitoral','Forbes Brasil — Geral','Interesses')
        self.assertEqual(app.classify(generic),'Brasil')
        self.assertFalse(app.is_relevant(generic))
        premium=article('lux','Hotel de luxo recebe investimento milionário','Hotelier News — Geral','Interesses')
        self.assertEqual(app.classify(premium),'Interesses')

    def test_state_is_not_capital(self):
        wrong=article('estado','Governo de São Paulo lança programa estadual de agricultura',
                      'Diário do Transporte — Notícias','São Paulo')
        self.assertEqual(app.classify(wrong),'Brasil')
        self.assertFalse(app.is_relevant(wrong))
        city=article('metro','CPTM terá nova estação na Linha 7-Rubi',
                      'Diário do Transporte — Notícias','São Paulo')
        self.assertTrue(app.is_relevant(city))
        self.assertEqual(app.classify(city),'São Paulo')
        bike=article('bike','Prefeitura de São Paulo anuncia expansão de ciclovias',
                      'Diário do Transporte — Notícias','São Paulo')
        self.assertEqual(app.classify(bike),'São Paulo')

    def test_rdf_support_date_and_no_description(self):
        xml=b'''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
        <item rdf:about="https://example.org/n"><title>Arquitetura e construcoes inovadoras</title><link>https://example.org/n?utm_medium=rss</link><dc:date>2026-10-13T10:05:00+00:00</dc:date><description>Material protegido</description></item>
        </rdf:RDF>'''
        values=app.parse_rss(xml,'ArchDaily Brasil — Arquitetura','Interesses')
        self.assertEqual(len(values),1)
        self.assertEqual(values[0]['publishedAt'],'2026-10-13T10:05:00+00:00')
        self.assertNotIn('description',values[0])
        self.assertNotIn('Material protegido',str(values))

    def test_category_balance_and_interest_diversity(self):
        items=[]
        for i in range(6):
            items.append(article('g1w'+str(i),f'China e Estados Unidos chegam a acordo comercial {i}', 'G1 — Mundo','Mundo'))
            items.append(article('agw'+str(i),f'Argentina e Mercosul discutem acordo internacional {i}', 'Agência Brasil — Internacional','Mundo'))
            items.append(article('cn'+str(i),f'Congresso debate reforma tributária e fiscal {i}', 'CNN Brasil','Brasil'))
            items.append(article('inf'+str(i),f'Banco Central analisa juros e inflação {i}', 'InfoMoney','Brasil'))
            items.append(article('sp'+str(i),f'Prefeitura de São Paulo anuncia nova obra de mobilidade {i}', 'Diário do Transporte — Notícias','São Paulo'))
            items.append(article('se'+str(i),f'Mercado imobiliário divulga índice de vendas de imóveis {i}', 'Secovi-SP — Notícias','Mercado imobiliário'))
            items.append(article('cb'+str(i),f'Construção civil registra alta em financiamentos imobiliários {i}', 'CBIC — Notícias','Mercado imobiliário'))
        interests=[
            ('arq','Novo projeto de arquitetura sustentável','ArchDaily Brasil — Arquitetura'),
            ('f1','Equipe anuncia novidades para o Grande Prêmio','Motorsport Brasil — Fórmula 1'),
            ('gas','Festival reúne chefs internacionais','Prazeres da Mesa — Gastronomia'),
            ('viag','Companhias lançam novas rotas aéreas','Melhores Destinos — Viagens'),
            ('lux','Ferrari apresenta lançamento exclusivo','Forbes Brasil — Geral')]
        for ident,title,feed in interests:items.append(article(ident,title,feed,'Interesses'))
        chosen,_=app.select(items,NOW)
        self.assertEqual(len(chosen),14)
        counts={cat:sum(x['category']==cat for x in chosen) for cat,_ in app.TARGETS}
        self.assertEqual(counts,dict(app.TARGETS))
        self.assertEqual(len({x['topic'] for x in chosen if x['category']=='Interesses'}),5)
        self.assertLessEqual(max(sum(x['source']==src for x in chosen) for src in {a['source'] for a in chosen}),2)
        self.assertTrue(all(x['contentType']=='noticia' for x in chosen))

    def test_excludes_articles_after_0730_sp_or_older_than_48h(self):
        good=article('good','Banco Central revisa inflação','InfoMoney','Brasil',hr=10)
        after=article('after','Banco Central revisa inflação e juros','InfoMoney','Brasil',hr=11)
        old=article('old','Banco Central revisa inflação e juros no país','InfoMoney','Brasil',hr=10,day='2026-10-09')
        chosen,_=app.select([good,after,old],NOW)
        self.assertEqual([x['id'] for x in chosen],['good'])

    def test_preview_only_path_and_output(self):
        self.assertIn('briefing_preview_07.json',str(app.OUT))
        self.assertNotEqual(app.OUT.name,'briefing.json')
        xml=(b'<rss><channel><item><title>Banco Central revisa taxa de juros e infla\xc3\xa7\xc3\xa3o</title>'
             b'<link>https://example.org/safe</link><pubDate>Tue, 13 Oct 2026 10:00:00 GMT</pubDate>'
             b'</item></channel></rss>')
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'preview.json'
            with patch.object(app,'fetch',return_value=xml):
                self.assertTrue(app.build(now=NOW,out=out))
            data=json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(data['previewVersion'],'0.7')
            self.assertLessEqual(len(data['items']),14)
            self.assertEqual(data['editionDate'],'2026-10-13')
            self.assertIn('coverage',data)
            self.assertNotIn('Texto integral',str(data))

if __name__=='__main__':unittest.main()

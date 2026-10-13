import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coletor import parse_rss, select, canonical

RSS=b'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Exemplo para TESTE</title>
<item><title>Novo projeto imobiliario em Sao Paulo para teste</title>
<link>https://example.org/noticias/teste?utm_source=rss</link>
<pubDate>Tue, 13 Oct 2026 10:10:00 GMT</pubDate><description>Texto de teste nao deve ser exposto</description></item>
<item><title>Noticias de turismo e viagens para teste</title>
<link>https://example.org/turismo/2</link>
<pubDate>Tue, 13 Oct 2026 10:12:00 GMT</pubDate></item>
<item><title>Noticia futura que nao entra no corte</title>
<link>https://example.org/futuro</link>
<pubDate>Tue, 13 Oct 2026 12:05:00 GMT</pubDate></item>
</channel></rss>'''

class FeedTests(unittest.TestCase):
    def test_parser_and_metadata(self):
        items=parse_rss(RSS,'Agencia de teste — Geral','Brasil')
        self.assertEqual(len(items),3)
        self.assertEqual(items[0]['url'],'https://example.org/noticias/teste')
        self.assertNotIn('description',items[0])
        self.assertNotIn('Texto de teste',str(items))
    def test_cutoff_and_categories(self):
        items=parse_rss(RSS,'Agencia de teste — Geral','Brasil')
        selected,day=select(items,datetime(2026,10,13,11,0,tzinfo=timezone.utc))
        self.assertEqual(day,'2026-10-13')
        self.assertEqual(len(selected),2)
        self.assertEqual({x['category'] for x in selected},{'São Paulo','Interesses'} if False else {'Mercado imobiliário','Interesses'})
    def test_dedupe(self):
        items=parse_rss(RSS,'Agencia de teste — Geral','Brasil')
        selected,_=select(items+items,datetime(2026,10,13,11,0,tzinfo=timezone.utc))
        self.assertEqual(len(selected),2)
    def test_excludes_lottery_and_football(self):
        news=[
            dict(id='loteria',title='Mega-Sena sorteia prêmio acumulado de R$ 150 milhões',url='https://example.org/l',publishedAt='2026-10-13T10:00:00+00:00',source='Agência Brasil',feed='Agência Brasil — Geral',baseCategory='Brasil'),
            dict(id='futebol',title='Copa do Brasil: Bragantino abre vantagem sobre Ferroviária',url='https://example.org/f',publishedAt='2026-10-13T10:00:00+00:00',source='Agência Brasil',feed='Agência Brasil — Esportes',baseCategory='Brasil'),
            dict(id='juros',title='Banco Central debate taxa de juros e inflação',url='https://example.org/j',publishedAt='2026-10-13T10:00:00+00:00',source='Agência Brasil',feed='Agência Brasil — Economia',baseCategory='Brasil'),
        ]
        chosen,_=select(news,datetime(2026,10,13,11,0,tzinfo=timezone.utc))
        self.assertEqual([n['id'] for n in chosen],['juros'])

    def test_no_stale_items_older_than_48h(self):
        news=[dict(id='stale',title='Nova exposição em São Paulo',url='https://example.org/c',publishedAt='2026-10-09T10:00:00+00:00',source='Agência Brasil',feed='Agência Brasil — Cultura',baseCategory='Interesses')]
        chosen,_=select(news,datetime(2026,10,13,11,0,tzinfo=timezone.utc))
        self.assertEqual(chosen,[])

    def test_keeps_formula_one(self):
        news=[dict(id='f1',title='Fórmula 1 anuncia novo calendário de grandes prêmios',url='https://example.org/f1',publishedAt='2026-10-13T10:00:00+00:00',source='Fonte',feed='Agência Brasil — Esportes',baseCategory='Interesses')]
        chosen,_=select(news,datetime(2026,10,13,11,0,tzinfo=timezone.utc))
        self.assertEqual(len(chosen),1)
        self.assertEqual(chosen[0]['category'],'Interesses')

    def test_relevance_over_recency(self):
        news=[
            dict(id='lot',title='Mega-Sena sorteia prêmio acumulado',url='https://example.org/l',publishedAt='2026-10-13T10:20:00+00:00',source='Fonte',feed='Agência Brasil — Geral',baseCategory='Brasil'),
            dict(id='local',title='Novo financiamento imobiliário em São Paulo',url='https://example.org/x',publishedAt='2026-10-13T08:00:00+00:00',source='Fonte',feed='Agência Brasil — Economia',baseCategory='Brasil'),
            dict(id='economic',title='Inflação e taxa de juros impactam o mercado',url='https://example.org/z',publishedAt='2026-10-13T10:10:00+00:00',source='Fonte',feed='Agência Brasil — Economia',baseCategory='Brasil')]
        chosen,_=select(news,datetime(2026,10,13,11,0,tzinfo=timezone.utc))
        self.assertEqual(chosen[0]['id'],'local')
        self.assertEqual({x['id'] for x in chosen},{'local','economic'})

    def test_canonical_rejects_javascript(self):
        self.assertIsNone(canonical('javascript:alert(1)'))

if __name__=='__main__':unittest.main()

# Extensões do piloto 0.4 — os testes usam somente dados sintéticos.
class NewSourcesTests(unittest.TestCase):
    def sample(self,id,title,feed,base):
        return dict(id=id,title=title,url='https://example.org/'+id,
                    publishedAt='2026-10-13T09:30:00+00:00',
                    source=feed.split(' — ')[0],feed=feed,baseCategory=base)
    def test_bbc_world_and_brazil(self):
        from coletor import classify
        self.assertEqual(classify(self.sample('b1','Acordo de paz internacional altera cenário da guerra', 'BBC News Brasil — Geral','Mundo')), 'Mundo')
        self.assertEqual(classify(self.sample('b2','Governo do Brasil anuncia medida econômica','BBC News Brasil — Geral','Mundo')), 'Brasil')
    def test_specialist_source_requires_specialist_title(self):
        from coletor import classify
        self.assertEqual(classify(self.sample('s1','Venda de imóveis e mercado imobiliário em São Paulo','Secovi-SP — Notícias','Mercado imobiliário')),'Mercado imobiliário')
        self.assertEqual(classify(self.sample('s2','Entidade promove seminário institucional','Secovi-SP — Notícias','Mercado imobiliário')),'Brasil')
    def test_sp_health_does_not_mean_city_news(self):
        from coletor import classify
        self.assertEqual(classify(self.sample('sp1','Campanha nacional de vacinação','Governo SP Saúde — Notícias','São Paulo')),'Brasil')
        self.assertEqual(classify(self.sample('sp2','Metrô de São Paulo inaugura nova linha','Governo SP Saúde — Notícias','São Paulo')),'São Paulo')
    def test_incomplete_categories_are_allowed(self):
        from coletor import select
        stories=[self.sample('f1','Fórmula 1 anuncia novo calendário','Agência Brasil — Esportes','Interesses')]
        chosen,_=select(stories,datetime(2026,10,13,11,0,tzinfo=timezone.utc))
        self.assertEqual(len(chosen),1)
        self.assertEqual(chosen[0]['category'],'Interesses')
    def test_licensed_feed_only_is_not_implicitly_true(self):
        from coletor import FEEDS
        self.assertGreater(len(FEEDS),6)
        self.assertEqual(len({url for _,_,url in FEEDS}),len(FEEDS))

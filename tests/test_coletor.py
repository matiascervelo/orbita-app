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


class DiagnosticRegressionTests(unittest.TestCase):
    def test_relevant_democracy_article_from_previous_evening(self):
        from coletor import select
        story=dict(id='publico',title='Milhares ocupam Copacabana em ato pela democracia',
                   url='https://example.org/evento',publishedAt='2026-10-12T22:04:00+00:00',
                   source='Agência Brasil',feed='Agência Brasil — Política',baseCategory='Brasil')
        chosen,_=select([story],datetime(2026,10,13,22,0,tzinfo=timezone.utc))
        self.assertEqual([x['id'] for x in chosen],['publico'])

    def test_preserves_prior_when_no_relevant_items_but_feed_is_healthy(self):
        import tempfile,json
        from unittest.mock import patch
        from coletor import build
        old='''<?xml version="1.0"?><rss><channel><item><title>Noticia genérica sem relevância</title><link>https://example.org/g</link><pubDate>Mon, 12 Oct 2026 20:00:00 GMT</pubDate></item></channel></rss>'''.encode('utf-8')
        previous={'editionDate':'2026-10-12','status':'ready','items':[{'id':'anterior'}]}
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'briefing.json';p.write_text(json.dumps(previous),encoding='utf-8')
            with patch('coletor.fetch',return_value=old):
                self.assertTrue(build(datetime(2026,10,13,22,0,tzinfo=timezone.utc),out=p))
            self.assertEqual(json.loads(p.read_text(encoding='utf-8')),previous)

    def test_all_feeds_failed_reports_error(self):
        import tempfile,json
        from unittest.mock import patch
        from coletor import build
        previous={'editionDate':'2026-10-12','status':'ready','items':[{'id':'anterior'}]}
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'briefing.json';p.write_text(json.dumps(previous),encoding='utf-8')
            with patch('coletor.fetch',side_effect=ConnectionError('offline')):
                self.assertFalse(build(datetime(2026,10,13,22,0,tzinfo=timezone.utc),out=p))
            self.assertEqual(json.loads(p.read_text(encoding='utf-8')),previous)

class OfficialSources05Tests(unittest.TestCase):
    def test_ibge_json_extracts_metadata_only(self):
        import json
        from coletor import parse_ibge_news
        raw=json.dumps({"items":[{"titulo":"IBGE divulga IPCA e custos da construção civil",
          "link":"https://agenciadenoticias.ibge.gov.br/agencia-noticias/1-test.html",
          "data_publicacao":"13/10/2026 07:05:00","introducao":"CORPO NÃO AUTORIZADO"}]}).encode()
        values=parse_ibge_news(raw)
        self.assertEqual(len(values),1)
        self.assertEqual(values[0]['source'],'IBGE')
        self.assertEqual(values[0]['publishedAt'],'2026-10-13T10:05:00+00:00')
        self.assertNotIn('introducao',values[0])
        self.assertNotIn('CORPO NÃO AUTORIZADO',str(values))

    def test_ibge_bad_item_skipped(self):
        from coletor import parse_ibge_news
        self.assertEqual(parse_ibge_news(b'{"items":[{"titulo":"Sem link","data_publicacao":"13/10/2026 07:05:00"}]}'),[])

    def test_ibge_economy_selection(self):
        import json
        from coletor import parse_ibge_news
        raw=json.dumps({"items":[{"titulo":"IBGE divulga IPCA e inflação no país",
          "link":"https://agenciadenoticias.ibge.gov.br/noticias/123",
          "data_publicacao":"13/10/2026 07:05:00"}]}).encode()
        selected,_=select(parse_ibge_news(raw), datetime(2026,10,13,12,tzinfo=timezone.utc))
        self.assertEqual(len(selected),1)
        self.assertEqual(selected[0]['category'],'Brasil')

    def test_sector_and_city_rss_classification(self):
        from coletor import classify
        sector={'title':'Mercado imobiliário de São Paulo tem nova pesquisa','baseCategory':'Mercado imobiliário','feed':'Secovi-SP — Notícias'}
        city={'title':'Metrô de São Paulo inaugura estação na capital','baseCategory':'São Paulo','feed':'Agência SP — Notícias'}
        generic={'title':'Governo estadual divulga concurso para outras cidades','baseCategory':'São Paulo','feed':'Agência SP — Notícias'}
        self.assertEqual(classify(sector),'Mercado imobiliário')
        self.assertEqual(classify(city),'São Paulo')
        self.assertEqual(classify(generic),'Brasil')

    def test_failing_new_feed_does_not_break_valid_feeds(self):
        import tempfile, json
        from unittest.mock import patch
        from coletor import build
        sample=(b'<?xml version="1.0"?><rss><channel><item>'
                b'<title>Banco Central altera perspectiva de juros e inflacao</title>'
                b'<link>https://example.org/economia</link>'
                b'<pubDate>Tue, 13 Oct 2026 09:00:00 GMT</pubDate>'
                b'</item></channel></rss>')
        def fake_fetch(url):
            if 'agenciabrasil' in url: return sample
            raise ConnectionError('feed em teste indisponível')
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'briefing.json'
            with patch('coletor.fetch',side_effect=fake_fetch):
                self.assertTrue(build(datetime(2026,10,13,12,0,tzinfo=timezone.utc),out=path))
            outcome=json.loads(path.read_text())
            self.assertEqual(outcome['status'],'ready')
            self.assertGreaterEqual(outcome['sourceFeedsOk'],1)
            self.assertEqual(outcome['sourceFeedsTotal'],11)


class Update051Tests(unittest.TestCase):
    def sample(self, article_id, title, category, hour=9, feed="Agência Brasil — Geral"):
        return dict(id=article_id,title=title,url="https://example.org/"+article_id,
                    publishedAt=f"2026-10-13T{hour:02}:00:00+00:00",
                    source="Agência Brasil",feed=feed,baseCategory=category)

    def test_ibge_gzip_api(self):
        import gzip, json
        from coletor import parse_ibge_news
        raw=json.dumps({"items":[{"titulo":"IBGE anuncia inflação e IPCA",
             "link":"https://example.org/ibge", "data_publicacao":"13/10/2026 07:05:00"}]}).encode()
        self.assertEqual(len(parse_ibge_news(gzip.compress(raw))),1)

    def test_gzip_rss_normalization(self):
        import gzip
        from coletor import normalize_response_bytes
        self.assertEqual(normalize_response_bytes(gzip.compress(RSS)), RSS)

    def test_global_relevance_without_legacy_keywords(self):
        item=self.sample("argentina","Jornalista é deportado da Argentina após críticas a Milei", "Mundo")
        chosen,_=select([item],datetime(2026,10,13,13,tzinfo=timezone.utc))
        self.assertEqual([s["id"] for s in chosen],["argentina"])

    def test_economy_world_and_local_by_context(self):
        stories=[
            self.sample("infra","Nova linha do metrô terá obra iniciada na capital", "São Paulo",feed="Agência SP — Notícias"),
            self.sample("imovel","Novo projeto imobiliário para residências", "Mercado imobiliário",feed="Secovi-SP — Notícias"),
            self.sample("geral","Instituição realiza seminário interno", "Brasil"),
        ]
        chosen,_=select(stories,datetime(2026,10,13,13,tzinfo=timezone.utc))
        self.assertEqual({s["id"] for s in chosen},{"infra","imovel"})

    def test_cutoff_still_holds_evening(self):
        articles=[
            self.sample("antes","Banco Central revisa inflação e juros", "Brasil",hour=10),
            self.sample("depois","Banco Central revisa inflação e juros após reunião", "Brasil",hour=19),
        ]
        chosen,_=select(articles,datetime(2026,10,13,23,tzinfo=timezone.utc))
        self.assertEqual([s["id"] for s in chosen],["antes"])

    def test_old_articles_not_filled_to_quota(self):
        old=self.sample("antigo","Banco Central altera inflação e juros", "Brasil",hour=10)
        old["publishedAt"]="2026-10-09T10:00:00+00:00"
        chosen,_=select([old],datetime(2026,10,13,23,tzinfo=timezone.utc))
        self.assertEqual(chosen,[])

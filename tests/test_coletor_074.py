"""Órbita 0.7.4: regressões da curadoria com dados sintéticos, sem internet."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import coletor_074 as app

NOW=datetime(2026,10,25,12,0,tzinfo=timezone.utc)  # 09:00 São Paulo

def make(title, ident='a', feed='CNN Brasil', base='Brasil', dt='2026-10-25T09:00:00+00:00'):
    return dict(id=ident,title=title,url='https://example.com/'+ident,
                publishedAt=dt,source=feed.split(' — ')[0],feed=feed,baseCategory=base)

class Orbita074LegacyTests(unittest.TestCase):
    def test_01_output_is_isolated(self):
        self.assertEqual(app.OUT.name,'briefing_preview_074.json')
        self.assertNotEqual(app.OUT.name,'briefing.json')
        self.assertEqual(sum(n for _,n in app.TARGETS),14)
    def test_02_only_three_new_rss_candidates(self):
        names=[x[0] for x in app.FEEDS]
        self.assertEqual(len(names),24)
        self.assertEqual(len(app.API_SOURCES),1)
        for n in ('Metrópoles — São Paulo','Metrô de São Paulo — Notícias','SindusCon-SP — Imobiliário'):
            self.assertIn(n,names)
        self.assertEqual(len(set(url for _,_,url in app.FEEDS)),len(app.FEEDS))
    def test_03_no_agencia_sp_500_in_rss(self):
        self.assertFalse(any('agenciasp.sp.gov.br/feed' in x[2] for x in app.FEEDS))
    def test_04_tse_avenida_paulista_not_sp(self):
        x=make('TSE manda retirar posts com fake news que associa Lula a ritual satânico na Avenida Paulista',
               feed='G1 — Política')
        self.assertFalse(app.is_city_story(x['title']))
        self.assertEqual(app.classify(x),'Brasil')
    def test_05_municipal_city_decision(self):
        x=make('Prefeitura de São Paulo aprova novo zoneamento em Pinheiros',feed='Metrópoles — São Paulo',base='São Paulo')
        self.assertTrue(app.is_city_story(x['title']))
        self.assertEqual(app.classify(x),'São Paulo')
    def test_06_asiatic_stocks_not_brazil(self):
        x=make('Bolsas da Ásia despencam com ações de tecnologia após inflação dos EUA')
        self.assertEqual(app.classify(x),'Mundo')
    def test_07_brazilian_exchange_stays_brazil(self):
        x=make('Ibovespa cai e ações brasileiras reagem à queda das bolsas da Ásia')
        self.assertEqual(app.classify(x),'Brasil')
    def test_08_foreign_tech_cnn(self):
        x=make('Nasdaq cai 3% após anúncio do banco central dos Estados Unidos')
        self.assertEqual(app.classify(x),'Mundo')
    def test_09_metro_no_location_but_local(self):
        x=make('Passagens do Metrô poderão ser pagas com Pix nas estações',feed='Metrô de São Paulo — Notícias',base='São Paulo')
        self.assertEqual(app.classify(x),'São Paulo')
        self.assertTrue(app.is_relevant(x))
    def test_10_metro_broader_cities_not_capital(self):
        x=make('Estação de Osasco terá serviço de ônibus gratuito',feed='Metrô de São Paulo — Notícias',base='São Paulo')
        self.assertNotEqual(app.classify(x),'São Paulo')
        self.assertFalse(app.is_relevant(x))
    def test_11_metro_irrelevant_promo_not_city(self):
        x=make('Metrômania: produtos para colecionadores',feed='Metrô de São Paulo — Notícias',base='São Paulo')
        self.assertNotEqual(app.classify(x),'São Paulo')
    def test_12_metropoles_interior_not_city(self):
        x=make('Câmara de Campinas vota mudança em ruas da cidade',feed='Metrópoles — São Paulo',base='São Paulo')
        self.assertFalse(app.is_relevant(x))
    def test_13_sinduscon_property_prices(self):
        x=make('Preços dos imóveis residenciais aceleram em outubro',feed='SindusCon-SP — Imobiliário',base='Mercado imobiliário')
        self.assertTrue(app.is_relevant(x))
        self.assertEqual(app.classify(x),'Mercado imobiliário')
    def test_14_sinduscon_inspections(self):
        x=make('SindusCon-SP sugere disponibilizar laudos pré-vistoria',feed='SindusCon-SP — Imobiliário',base='Mercado imobiliário')
        self.assertTrue(app.is_relevant(x))
        self.assertEqual(app.classify(x),'Mercado imobiliário')
    def test_15_sinduscon_not_irrelevant(self):
        x=make('Aniversário da diretoria reúne convidados',feed='SindusCon-SP — Imobiliário',base='Mercado imobiliário')
        self.assertFalse(app.is_relevant(x))
    def test_16_secovi_construction_financing(self):
        x=make('Novas regras de crédito habitacional estimulam lançamentos residenciais',feed='Secovi-SP — Notícias',base='Mercado imobiliário')
        self.assertTrue(app.is_relevant(x))
        self.assertEqual(app.classify(x),'Mercado imobiliário')
    def test_17_cbic_cib_original(self):
        x=make('Reforma Tributária: entenda o Cadastro Imobiliário Brasileiro (CIB) e os impactos para a construção',feed='CBIC — Notícias',base='Mercado imobiliário')
        self.assertTrue(app.is_relevant(x))
        self.assertEqual(app.classify(x),'Mercado imobiliário')
    def test_18_cbic_event_is_excluded(self):
        x=make('CBIC reúne setor da construção em Goiânia para debater cenário econômico, habitação e investimentos no Centro-Oeste',feed='CBIC — Notícias',base='Mercado imobiliário')
        self.assertFalse(app.is_relevant(x))
    def test_19_stale_traffic_not_selected(self):
        x=make('Rodízio fica suspenso nesta quarta-feira em São Paulo',feed='Diário do Transporte — Notícias',base='São Paulo',dt='2026-10-21T12:00:00+00:00')
        self.assertTrue(app.is_expired_notice(x,NOW))
    def test_20_pope_not_tourism(self):
        x=make('Viagem do papa ao exterior pode ser adiada')
        self.assertIsNone(app.interest_topic(x))
    def test_21_marketing_f1_excluded(self):
        x=make('F1: McDonald’s e Red Bull lançam miniaturas colecionáveis',feed='Motorsport Brasil — Fórmula 1',base='Interesses')
        self.assertFalse(app.is_relevant(x))
    def test_22_headline_not_automatically_luxury(self):
        x=make('Forbes explica pesquisa eleitoral no Brasil',feed='Forbes Brasil — Geral',base='Interesses')
        self.assertFalse(app.is_relevant(x))
    def test_23_selection_cutoff_still_0730(self):
        a=make('Prefeitura de São Paulo anuncia grandes obras de infraestrutura',ident='a',feed='Diário do Transporte — Notícias',base='São Paulo',dt='2026-10-25T10:29:00+00:00')
        b=make('Prefeitura de São Paulo inaugura nova avenida e corredor de ônibus',ident='b',feed='Diário do Transporte — Notícias',base='São Paulo',dt='2026-10-25T10:31:00+00:00')
        selected,_=app.select([a,b],NOW)
        self.assertIn('a',[i['id'] for i in selected])
        self.assertNotIn('b',[i['id'] for i in selected])
    def test_24_news_older_than_48h_not_in_daily_briefing(self):
        a=make('SindusCon-SP confirma crescimento no financiamento imobiliário',ident='old',feed='SindusCon-SP — Imobiliário',base='Mercado imobiliário',dt='2026-10-20T09:00:00+00:00')
        selected,_=app.select([a],NOW)
        self.assertEqual(selected,[])
    def test_25_feed_accepts_rss_sample(self):
        x=b'<rss version="2.0"><channel><item><title>Financiamento imobiliario sobe em SP</title><link>https://example.com/1</link><pubDate>Sun, 25 Oct 2026 07:00:00 GMT</pubDate></item></channel></rss>'
        got=app.parse_rss(x,'SindusCon-SP — Imobiliário','Mercado imobiliário')
        self.assertEqual(len(got),1)
    def test_26_feed_accepts_atom_sample(self):
        x=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Metro de SP amplia linha</title><link href="https://example.com/metro" rel="alternate"/><updated>2026-10-25T07:00:00Z</updated></entry></feed>'
        got=app.parse_rss(x,'Metrô de São Paulo — Notícias','São Paulo')
        self.assertEqual(len(got),1)
    def test_27_diagnostic_json_keeps_sector_samples(self):
        import io, contextlib
        fixture='<rss version="2.0"><channel><item><title>Financiamentos imobiliários crescem em outubro</title><link>https://example.com/a</link><pubDate>Sun, 25 Oct 2026 09:00:00 GMT</pubDate></item></channel></rss>'.encode('utf-8')
        def simulated_get(url):
            return fixture
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'preview.json'
            with patch.object(app,'fetch',simulated_get),contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(app.build(NOW,out=target))
            data=json.loads(target.read_text('utf-8'))
            self.assertEqual(data['previewVersion'],'0.7.4')
            self.assertIn('sectorEditorialSamples',data)
            self.assertTrue(data['editorialDiagnostics']['trendCandidatesAreNotPublished'])
            self.assertEqual(data['sourceFeedsTotal'],25)
    def test_28_analysis_candidates_not_news(self):
        with tempfile.TemporaryDirectory() as td:
            feed='<rss version="2.0"><channel><item><title>Preços dos imóveis residenciais aceleram em outubro</title><link>https://example.com/analysis</link><pubDate>Tue, 20 Oct 2026 09:00:00 GMT</pubDate></item></channel></rss>'.encode('utf-8')
            def fake_fetch(url):return feed
            with patch.object(app,'fetch',fake_fetch):
                app.build(NOW,out=Path(td)/'preview.json')
            d=json.loads((Path(td)/'preview.json').read_text())
            self.assertEqual(len(d['items']),0)
            self.assertTrue(any(x['feed'].startswith('SindusCon') for x in d['trendCandidatesForReviewOnly']))

class Orbita074NewTests(unittest.TestCase):
    def test_29_last_days_offer_rejected(self):
        x=make('Últimos dias! Accor Explorer oferece R$ 352 em crédito de hospedagem e 2 noites grátis',
               feed='Melhores Destinos — Viagens',base='Interesses')
        self.assertEqual(app.rejection_reason(x,NOW),'oferta_comercial_de_viagem')

    def test_30_public_credit_rule_not_promotion(self):
        x=make('BC reforça regras de proteção ao consumidor nas ofertas de crédito',feed='Agência Brasil — Economia')
        self.assertIsNone(app.low_value_reason_074(x['title']))
        self.assertTrue(app.is_relevant(x,NOW))

    def test_31_service_returned_to_normal_rejected(self):
        x=make('Linha 9-Esmeralda tem operação normalizada após alagamento em Santo Amaro',
               feed='Diário do Transporte — Notícias',base='São Paulo')
        self.assertEqual(app.rejection_reason(x,NOW),'operacao_ja_normalizada')

    def test_32_metro_new_station_still_allowed(self):
        x=make('Metrô de São Paulo inaugura nova estação da Linha 2-Verde',
               feed='Metrô de São Paulo — Notícias',base='São Paulo')
        self.assertTrue(app.is_relevant(x,NOW))

    def test_33_old_market_report_qualified(self):
        x=make('Pesquisa Mensal do Mercado Imobiliário – Agosto 2026',ident='report',
               feed='Secovi-SP — Notícias',base='Mercado imobiliário',
               dt='2026-10-15T19:20:05+00:00')
        cutoff=app.datetime(2026,10,25,10,30,tzinfo=timezone.utc)
        self.assertTrue(app.is_panorama_candidate(x,cutoff))
        got=app.select_panorama([x],cutoff,[])
        self.assertEqual(len(got),1)
        self.assertEqual(got[0]['contentType'],'panorama')
        self.assertTrue(got[0]['notBreakingNews'])
        self.assertEqual(got[0]['publishedDateSP'],'2026-10-15')

    def test_34_meeting_only_not_report(self):
        x=make('CBIC debate inflação, crédito imobiliário e os impactos para a construção em 2027',
               feed='CBIC — Notícias',base='Mercado imobiliário',
               dt='2026-10-22T20:05:54+00:00')
        self.assertFalse(app.is_panorama_candidate(x,app.datetime(2026,10,25,10,30,tzinfo=timezone.utc)))

    def test_35_old_study_not_added_to_today(self):
        x=make('Pesquisa Mensal do Mercado Imobiliário – Agosto 2026',ident='report',
               feed='Secovi-SP — Notícias',base='Mercado imobiliário',
               dt='2026-10-15T19:20:05+00:00')
        selected,_=app.select([x],NOW)
        self.assertEqual(selected,[])

    def test_36_over_14_days_not_panorama(self):
        x=make('Pesquisa Mensal do Mercado Imobiliário – Julho 2026',
               feed='Secovi-SP — Notícias',base='Mercado imobiliário',
               dt='2026-10-08T11:00:00+00:00')
        self.assertFalse(app.is_panorama_candidate(x,app.datetime(2026,10,25,10,30,tzinfo=timezone.utc)))

    def test_37_panorama_cap_three_and_source_diversity(self):
        cutoff=app.datetime(2026,10,25,10,30,tzinfo=timezone.utc)
        titles=[
            ('Pesquisa Mensal do Mercado Imobiliário – Agosto 2026','Secovi-SP — Notícias'),
            ('Vendas de imóveis em São Paulo sobem em julho','SindusCon-SP — Imobiliário'),
            ('Índice nacional de preços residenciais acelera','CBIC — Notícias'),
            ('Levantamento sobre venda de imóveis em capitais','Secovi-SP — Notícias'),
            ('Pesquisa de lançamentos de imóveis em SP','SindusCon-SP — Imobiliário'),
        ]
        items=[make(t,ident=str(i),feed=f,base='Mercado imobiliário',dt='2026-10-15T19:20:05+00:00')
               for i,(t,f) in enumerate(titles)]
        chosen=app.select_panorama(items,cutoff,[])
        self.assertEqual(len(chosen),3)
        self.assertEqual(len({x['source'] for x in chosen}),3)

    def test_38_same_article_not_in_both_sections(self):
        cutoff=app.datetime(2026,10,25,10,30,tzinfo=timezone.utc)
        x=make('Pesquisa Mensal do Mercado Imobiliário – Agosto 2026',ident='report',
               feed='Secovi-SP — Notícias',base='Mercado imobiliário',
               dt='2026-10-15T19:20:05+00:00')
        self.assertEqual(app.select_panorama([x],cutoff,[{'id':'report'}]),[])

    def test_39_empty_panorama_allowed(self):
        cutoff=app.datetime(2026,10,25,10,30,tzinfo=timezone.utc)
        self.assertEqual(app.select_panorama([],cutoff,[]),[])

    def test_40_complete_preview_contains_dates_and_feed_age(self):
        import contextlib,io
        t1='<rss version="2.0"><channel><item><title>Pesquisa Mensal do Mercado Imobiliário - Agosto 2026</title><link>https://example.com/report</link><pubDate>Thu, 15 Oct 2026 19:20:05 GMT</pubDate></item></channel></rss>'.encode()
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'preview_074.json'
            with patch.object(app,'fetch',lambda url:t1), contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                self.assertTrue(app.build(NOW,out=out))
            data=json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(data['previewVersion'],'0.7.4')
            self.assertTrue(data['editorialDiagnostics']['panoramaSeparateFromDailyNews'])
            self.assertTrue(data['editorialDiagnostics']['panoramaPreviewOnly'])
            self.assertEqual(data['panoramaWindowDays'],14)
            self.assertGreaterEqual(len(data['panoramaImobiliario']),1)
            diag=data['feedDiagnostics'][0]
            self.assertIn('latestBeforeCutoff',diag)
            self.assertIn('newestAgeDays',diag)
            self.assertGreater(diag['newestAgeDays'],2)
            self.assertEqual(data['items'],[])

    def test_41_preview_only_no_active_briefing_changes(self):
        self.assertNotEqual(app.OUT.name,'briefing.json')
        self.assertEqual(app.OUT.name,'briefing_preview_074.json')

    def test_42_no_fulltext_in_panorama(self):
        cutoff=app.datetime(2026,10,25,10,30,tzinfo=timezone.utc)
        x=make('Pesquisa Mensal do Mercado Imobiliário – Agosto 2026',ident='a',
               feed='Secovi-SP — Notícias',base='Mercado imobiliário',
               dt='2026-10-15T19:20:05+00:00')
        chosen=app.select_panorama([x],cutoff,[])
        self.assertEqual(len(chosen),1)
        self.assertFalse(any(k in chosen[0] for k in ('description','content','summary','image')))

if __name__=='__main__':unittest.main()

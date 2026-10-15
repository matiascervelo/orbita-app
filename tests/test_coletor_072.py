"""Órbita 0.7.2: testes de curadoria 100% offline, sem conexão ou alterações no site."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import coletor_072 as app

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def article(ident, title, feed='Agência Brasil — Economia', base='Brasil', hour=9, date='2026-10-14'):
    return {
        'id': ident,
        'title': title,
        'url': 'https://exemplo.org/noticia/' + ident,
        'publishedAt': f'{date}T{hour:02d}:00:00+00:00',
        'source': feed.split(' — ')[0],
        'feed': feed,
        'baseCategory': base,
    }


class Orbita072RegressionTests(unittest.TestCase):
    def test_no_publication_and_unmodified_07(self):
        self.assertEqual(app.OUT.name, 'briefing_preview_072.json')
        self.assertNotEqual(app.OUT.name, 'briefing.json')
        self.assertEqual(sum(n for _, n in app.TARGETS), 14)
        self.assertIn('0.7.2', app.__doc__)

    def test_new_city_feeds_are_explicitly_candidate_only(self):
        names = [name for name, _, _ in app.FEEDS]
        self.assertEqual(len(names), 21)
        self.assertEqual(len({url for _, _, url in app.FEEDS}), len(app.FEEDS))
        self.assertIn('Agência Mural — Grande São Paulo', names)
        self.assertIn('Jornal da USP — Notícias', names)
        self.assertIn('Diário do Transporte — Metropolitano SP', names)

    def test_city_specific_titles(self):
        for title in (
            'Prefeitura de São Paulo aprova novo corredor de ônibus',
            'Subprefeitura faz obras no bairro de Sapopemba',
            'Nova estação da Linha 6-Laranja entra em testes',
            'Infraestrutura da Avenida Paulista será renovada',
        ):
            with self.subTest(title=title):
                self.assertTrue(app.is_city_story(title))

    def test_does_not_confuse_state_or_neighbor_cities_with_capital(self):
        for title in (
            'Governo de São Paulo lança programa estadual de agricultura',
            'Prefeitura de Campinas inaugura nova avenida',
            'Ônibus de Guarulhos recebem novo sistema de bilhetagem',
            'Santo André terá nova linha de transporte urbano',
            'Linha 9-Esmeralda terá mudanças no atendimento em Osasco',
            'São Paulo anuncia benefícios à agricultura paulista',
        ):
            with self.subTest(title=title):
                self.assertFalse(app.is_city_story(title))

    def test_city_story_published_by_local_source(self):
        for src in ('Agência Mural — Grande São Paulo',
                    'Diário do Transporte — Metropolitano SP',
                    'Jornal da USP — Notícias'):
            item = article('cidade'+src, 'Prefeitura de São Paulo anuncia obra de mobilidade urbana',
                           src, 'São Paulo')
            self.assertEqual(app.classify(item), 'São Paulo')
            self.assertTrue(app.is_relevant(item))

    def test_previous_preview_4_weak_stories_are_excluded(self):
        previous = (
            ('CBIC reúne setor da construção em Goiânia para debater cenário econômico, habitação e investimentos no Centro-Oeste',
             'CBIC — Notícias', 'Mercado imobiliário'),
            ('F1: McDonald’s e Red Bull lançam O Pit Stop Perfeito com novas miniaturas colecionáveis',
             'Motorsport Brasil — Fórmula 1', 'Interesses'),
            ('6a edição do congresso Entre Nós acontece em novembro em Itajaí',
             'Prazeres da Mesa — Gastronomia', 'Interesses'),
            ('Nova porta-voz da Casa Branca confunde Trump com marido e diz que queria trabalhar para o presidente dos EUA',
             'G1 — Mundo', 'Mundo'),
        )
        for i, (title, feed, cat) in enumerate(previous):
            with self.subTest(title=title):
                self.assertFalse(app.is_relevant(article(str(i), title, feed, cat)))

    def test_keep_significant_past_articles(self):
        good = (
            ('Reforma Tributária: entenda o Cadastro Imobiliário Brasileiro e os impactos para a construção',
             'CBIC — Notícias','Mercado imobiliário'),
            ('F1: Mercedes confirma carros atualizados no GP dos EUA',
             'Motorsport Brasil — Fórmula 1','Interesses'),
            ('Dólar sobe 0,74% e volta a fechar acima de R$ 5',
             'Agência Brasil — Economia','Brasil'),
            ('Aena assume o Galeão e anuncia R$ 1 bilhão em investimentos',
             'Melhores Destinos — Viagens','Interesses'),
        )
        for i, (title, feed, cat) in enumerate(good):
            with self.subTest(title=title):
                self.assertTrue(app.is_relevant(article('k'+str(i), title, feed, cat)))

    def test_luxury_is_not_any_forbes_headline(self):
        politics = article('politica', 'Senadores debatem reforma eleitoral',
                           'Forbes Brasil — Geral', 'Interesses')
        luxury = article('luxo', 'Hotel de luxo recebe investimento de R$ 500 milhões',
                         'Hotelier News — Geral', 'Interesses')
        self.assertFalse(app.is_relevant(politics))
        self.assertEqual(app.classify(politics), 'Brasil')
        self.assertTrue(app.is_relevant(luxury))
        self.assertEqual(app.classify(luxury), 'Interesses')
        self.assertEqual(app.interest_topic(luxury), 'Mercado de luxo')

    def test_selected_articles_do_not_fill_with_low_quality_news(self):
        headlines = [
            article('s1','F1: McDonald’s lança miniaturas colecionáveis',
                    'Motorsport Brasil — Fórmula 1','Interesses'),
            article('s2','Governo de São Paulo incentiva agricultura estadual',
                    'Diário do Transporte — Notícias','São Paulo'),
        ]
        chosen, _ = app.select(headlines, NOW)
        self.assertEqual(chosen, [])

    def test_diverse_world_sources_if_available(self):
        items = [
            article('w1', 'China e EUA aprovam acordo sobre tarifas comerciais', 'G1 — Mundo','Mundo'),
            article('w2', 'China e EUA lançam plano econômico', 'G1 — Mundo','Mundo'),
            article('w3', 'Mercosul e Argentina negociam novo acordo internacional',
                    'Agência Brasil — Internacional','Mundo'),
        ]
        chosen, _ = app.select(items, NOW)
        world = [x for x in chosen if x['category'] == 'Mundo']
        self.assertEqual(len(world), 2)
        self.assertEqual(len({x['source'] for x in world}), 2)

    def test_all_editorial_sections_if_legitimate_content_is_available(self):
        items = []
        for i in range(4):
            items += [
                article(f'm{i}',f'China e EUA anunciam acordo econômico e tarifas comerciais {i}',
                        'G1 — Mundo' if i%2 == 0 else 'Agência Brasil — Internacional', 'Mundo'),
                article(f'b{i}',f'Banco Central revisa inflação, juros e dólar {i}',
                        'Agência Brasil — Economia' if i%2 == 0 else 'InfoMoney — Geral', 'Brasil'),
                article(f'sp{i}',f'Prefeitura de São Paulo anuncia obra na Linha 6-Laranja {i}',
                        'Diário do Transporte — Notícias' if i%2 == 0 else 'Agência Mural — Grande São Paulo', 'São Paulo'),
                article(f'im{i}',f'Mercado imobiliário divulga relatório de vendas de imóveis {i}',
                        'CBIC — Notícias' if i%2 == 0 else 'Secovi-SP — Notícias', 'Mercado imobiliário'),
            ]
        items.extend([
            article('f1','F1: Equipe muda estratégia para o Grande Prêmio','Motorsport Brasil — Fórmula 1','Interesses'),
            article('arq','Arquitetura sustentável ganha espaço nos escritórios','ArchDaily Brasil — Arquitetura','Interesses'),
            article('gas','Restaurantes Michelin ampliam cardápios e alta gastronomia','Prazeres da Mesa — Gastronomia','Interesses'),
            article('viag','Novas rotas internacionais ampliam opções de viagens','Melhores Destinos — Viagens','Interesses'),
            article('lux','Hotel de luxo inaugura novas suítes exclusivas','Hotelier News — Geral','Interesses'),
        ])
        chosen, day = app.select(items, NOW)
        self.assertEqual(day, '2026-10-14')
        self.assertEqual(len(chosen),14)
        self.assertEqual({k:sum(x['category']==k for x in chosen) for k,_ in app.TARGETS},dict(app.TARGETS))
        self.assertEqual(len({x['topic'] for x in chosen if x['category']=='Interesses'}),5)
        self.assertLessEqual(max(sum(x['source']==src for x in chosen) for src in {a['source'] for a in chosen}),2)

    def test_0730_sp_cutoff_and_48h_window(self):
        stories = [
            article('before','Banco Central decide juros e Selic','InfoMoney — Geral','Brasil',hour=10),
            article('after','Banco Central decide nova Selic','InfoMoney — Geral','Brasil',hour=11),
            article('old','Banco Central publica decisão de juros','InfoMoney — Geral','Brasil',hour=9,date='2026-10-09'),
        ]
        chosen, _ = app.select(stories, NOW)
        self.assertEqual([x['id'] for x in chosen], ['before'])

    def test_parser_does_not_copy_body_or_description(self):
        xml = b'''<rss><channel><item><title>Banco Central aprova nova taxa Selic</title>
            <link>https://exemplo.org/n?utm_medium=rss</link>
            <pubDate>Wed, 14 Oct 2026 09:00:00 GMT</pubDate>
            <description>Texto de terceiros, nao republicar</description>
            </item></channel></rss>'''
        result=app.parse_rss(xml,'Agência Brasil — Economia','Brasil')
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['url'],'https://exemplo.org/n')
        self.assertNotIn('description',result[0])
        self.assertNotIn('Texto de terceiros',str(result))

    def test_network_failure_does_not_publish_or_hide_errors(self):
        xml=(b'<rss><channel><item><title>Banco Central revisa taxa Selic e inflacao</title>'
             b'<link>https://exemplo.org/safe</link>'
             b'<pubDate>Wed, 14 Oct 2026 09:00:00 GMT</pubDate></item></channel></rss>')
        def fake_fetch(url):
            if 'ibge' in url: raise OSError('TLS certificate rejected')
            return xml
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'preview.json'
            with patch.object(app, 'fetch', side_effect=fake_fetch):
                self.assertTrue(app.build(now=NOW,out=out))
            data=json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(data['previewVersion'],'0.7.2')
            self.assertIn('editorialDiagnostics', data)
            self.assertEqual(data['sourceFeedsTotal'],22)
            self.assertEqual(len(data['feedDiagnostics']),22)
            self.assertTrue(any('IBGE' in message for message in data['warnings']))
            self.assertIn('newCandidateFeeds',data)
            self.assertTrue(all('body' not in x and 'summary' not in x for x in data['items']))
            self.assertFalse((Path(d)/'briefing.json').exists())



class Orbita072EditorialTests(unittest.TestCase):
    # Corte: quinta-feira 15/10/2026 às 7h30 de São Paulo = 10h30 UTC.
    THURSDAY_NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    CUTOFF = datetime(2026, 10, 15, 10, 30, tzinfo=timezone.utc)

    def local_item(self, ident, title, day='2026-10-14', hour=20, feed='Diário do Transporte — Notícias'):
        return article(ident, title, feed, 'São Paulo', hour=hour, date=day)

    def test_expired_rodizio_from_previous_day_is_removed(self):
        old=self.local_item('oldrod', 'URGENTE: Prefeitura de São Paulo suspende rodízio de veículos na tarde e noite desta quarta-feira (14) por causa das fortes chuvas')
        self.assertTrue(app.is_expired_notice(old,self.CUTOFF))
        self.assertEqual(app.rejection_reason(old,self.CUTOFF),'aviso_ja_vencido')
        chosen,_=app.select([old],self.THURSDAY_NOW)
        self.assertEqual(chosen,[])

    def test_same_day_alert_is_not_expired(self):
        today=self.local_item('today','Prefeitura de São Paulo suspende rodízio nesta quinta-feira (15)',day='2026-10-15',hour=9)
        self.assertFalse(app.is_expired_notice(today,self.CUTOFF))
        self.assertTrue(app.is_relevant(today,self.CUTOFF))

    def test_tomorrow_notice_and_new_permanent_rule_survive(self):
        tomorrow=self.local_item('tom','Prefeitura de São Paulo suspende rodízio amanhã (15)')
        permanent=self.local_item('perm','Prefeitura de São Paulo anuncia novas regras permanentes para rodízio a partir de novembro')
        self.assertFalse(app.is_expired_notice(tomorrow,self.CUTOFF))
        self.assertFalse(app.is_expired_notice(permanent,self.CUTOFF))

    def test_undated_metro_notice_does_not_get_arbitrary_expiration(self):
        a=self.local_item('undated','Metrô de São Paulo anuncia suspensão de serviço para obras')
        self.assertFalse(app.is_expired_notice(a,self.CUTOFF))

    def test_papal_diplomatic_travel_is_not_tourism(self):
        papa=article('papa','Viagem do papa à América Latina pode ser adiada por saúde de Leão XIV, diz presidente do Peru','G1 — Mundo','Mundo')
        self.assertIsNone(app.interest_topic(papa))
        self.assertEqual(app.classify(papa),'Mundo')
        minister=article('min','Presidente fará viagem oficial aos Estados Unidos para negociação diplomática', 'G1 — Mundo','Mundo')
        self.assertIsNone(app.interest_topic(minister))
        self.assertEqual(app.classify(minister),'Mundo')

    def test_actual_tourism_stays_in_interests(self):
        for headline in ('Passagens aéreas para a Europa ficam mais baratas',
                         'Turismo no Brasil cresce com abertura de novos destinos',
                         'Companhia aérea inaugura voo direto para Madri'):
            with self.subTest(headline=headline):
                a=article('travel'+str(len(headline)),headline,'G1 — Mundo','Mundo')
                self.assertEqual(app.interest_topic(a),'Viagens')
                self.assertEqual(app.classify(a),'Interesses')
        a=article('holidays','Melhores destinos para férias de outubro','Melhores Destinos — Viagens','Interesses')
        self.assertEqual(app.interest_topic(a),'Viagens')

    def test_maceio_company_event_excluded_but_regulatory_news_preserved(self):
        event=article('maceio', 'Ademi-AL: Immobi Connection acontece nesta quinta e reúne especialistas do mercado imobiliário em Maceió', 'CBIC — Notícias','Mercado imobiliário')
        self.assertEqual(app.rejection_reason(event,self.CUTOFF),'convite_ou_evento_sem_noticia')
        law=article('law','Congresso aprova novas regras de crédito imobiliário durante conferência', 'CBIC — Notícias','Mercado imobiliário')
        self.assertTrue(app.is_relevant(law,self.CUTOFF))

    def test_forbes_economy_without_luxury_does_not_displace_brazil_feeds(self):
        soy=article('soy','Importações de soja pela China caem 7,7% em setembro em relação ao ano anterior', 'Forbes Brasil — Geral','Interesses')
        self.assertEqual(app.rejection_reason(soy,self.CUTOFF),'veiculo_geral_sem_assunto_de_luxo')
        luxury=article('luxry','Mansão de luxo de R$ 29 milhões é colocada à venda', 'Forbes Brasil — Geral','Interesses')
        self.assertTrue(app.is_relevant(luxury,self.CUTOFF))
        self.assertEqual(app.interest_topic(luxury),'Mercado de luxo')

    def test_sao_paulo_two_distinct_publishers_preferred(self):
        stories=[
            self.local_item('sp1','Prefeitura de São Paulo anuncia nova linha de ônibus e obras de infraestrutura',hour=8),
            self.local_item('sp2','Metrô de São Paulo recebe nova estação e investimentos',hour=9),
            article('sp3','Prefeitura de São Paulo autoriza obras de mobilidade urbana e novos investimentos','CNN Brasil','Brasil',hour=9),
        ]
        selected,_=app.select(stories,self.THURSDAY_NOW)
        city=[x for x in selected if x['category']=='São Paulo']
        self.assertEqual(len(city),2)
        self.assertEqual(len({x['source'] for x in city}),2)

    def test_diversity_falls_back_when_only_one_publisher_available(self):
        stories=[
            self.local_item('sp1','Prefeitura de São Paulo anuncia nova linha de ônibus e obras de infraestrutura',hour=8),
            self.local_item('sp2','Metrô de São Paulo recebe nova estação e investimentos',hour=9),
        ]
        selected,_=app.select(stories,self.THURSDAY_NOW)
        self.assertEqual(len([x for x in selected if x['category']=='São Paulo']),2)

    def test_real_previous_preview_negative_samples(self):
        bad=[
            self.local_item('bad1','URGENTE: Prefeitura de São Paulo suspende rodízio de veículos na tarde e noite desta quarta-feira (14) por causa das fortes chuvas'),
            article('bad2','Ademi-AL: Immobi Connection acontece nesta quinta e reúne especialistas do mercado imobiliário em Maceió','CBIC — Notícias','Mercado imobiliário',date='2026-10-14',hour=18),
            article('bad3','Importações de soja pela China caem 7,7% em Setembro em Relação Ao Ano Anterior','Forbes Brasil — Geral','Interesses',date='2026-10-14',hour=13),
        ]
        for a in bad:self.assertIsNotNone(app.rejection_reason(a,self.CUTOFF))
        chosen,_=app.select(bad,self.THURSDAY_NOW)
        self.assertFalse(chosen)

    def test_no_paid_services_or_auto_publication(self):
        self.assertEqual(app.OUT.name,'briefing_preview_072.json')
        self.assertFalse(any('api.openai.com' in url for _,_,url in app.FEEDS+app.API_SOURCES))
        self.assertEqual(sum(x[1] for x in app.TARGETS),14)

if __name__ == '__main__': unittest.main()

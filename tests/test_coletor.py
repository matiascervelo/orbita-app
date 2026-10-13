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
    def test_canonical_rejects_javascript(self):
        self.assertIsNone(canonical('javascript:alert(1)'))

if __name__=='__main__':unittest.main()

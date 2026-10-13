# Órbita — piloto RSS gratuito 0.2

**Objetivo:** sair do protótipo com manchetes inventadas para um aplicativo pessoal que exibe dados RSS reais, quando a coleta tiver sido executada com sucesso, mantendo a identidade visual B.

## O que funciona nesta entrega

- Interface PWA para Android e desktop, nas cores grafite, azul cobalto e ciano, com Plus Jakarta Sans.
- Leitura de `data/briefing.json` gerado por um coletor Python sem bibliotecas externas.
- Coleta de feeds oficiais da Agência Brasil por assunto: Internacional, Economia, Política, Geral, Cultura e Esportes.
- Mostra **apenas título, veículo, data e link original**: sem publicar imagens ou corpo do artigo, sem criar resumos ou informações fictícias.
- Classificação experimental de notícias para Mundo, Brasil, São Paulo, Mercado imobiliário e Interesses; deduplicação de títulos e URLs; meta de até 14 notícias.
- Corte das notícias às 7h30 no fuso `America/Sao_Paulo`. O app libera a edição do dia a partir das 8h.
- Fav, preferências e tema escuro/claro salvos localmente no aparelho.
- Arquivo opcional `.github/workflows/atualizar.yml` para tentar coletar diariamente via GitHub Actions Free.

## O que **não** está pronto

- Coleta online validada neste ambiente (a conexão externa do ambiente de execução está indisponível); os feeds foram localizados no diretório oficial, mas precisam ser testados no ambiente com internet.
- Cobertura suficiente de imóveis, notícias locais de SP e Fórmula 1; fonte principal não basta sozinha.
- Resumo por IA, explicação “Por que importa”, frase “Para conversar”, verificação editorial de cada notícia, onboarding público e autenticação.
- Push às 8h: **não foi implementado**; workflows agendados podem atrasar ou falhar, portanto a chegada pontual é incerta.
- Histórico completo e sincronização entre aparelhos.
- Liberação para SaaS comercial: fontes, direitos de conteúdo e regras de hospedagem ainda precisam de análise.

## Executar localmente

Abra um terminal dentro desta pasta e rode:

```sh
python coletor.py
python -m http.server 8000
```

O primeiro comando necessita de conexão com a internet e tenta atualizar o arquivo `data/briefing.json`. Se os feeds estiverem indisponíveis, o coletor preserva a última edição que tiver manchetes e sai com erro, sem inventar conteúdo. No navegador, abra http://localhost:8000.

Para executar testes sem acesso à internet:

```sh
python -m unittest discover -s tests -v
```

## Testar gratuitamente no Android com GitHub

Apenas para o **piloto pessoal/educacional**, sem monetização e sem dados sensíveis:

1. Criar uma conta gratuita em https://github.com/ (caso não tenha).
2. Criar um repositório **público** chamado `orbita-piloto`; incluir todos os arquivos desta pasta (inclusive `.github/workflows/atualizar.yml`). **Atenção:** o conteúdo do repositório e a edição agregada serão públicos, ainda que preferências locais no seu Android não sejam sincronizadas.
3. Na aba **Actions**, executar manualmente o workflow *Atualizar manchetes gratuitas* para testar a coleta. Não supor que RSS ou hospedagem funcionam sem esse teste.
4. Nas configurações do repositório, abrir **Settings > Pages** e escolher **Deploy from a branch > main > /(root)**. Depois de publicada, visitar o endereço de GitHub Pages informado pelo próprio GitHub.
5. No Chrome do Android, abrir o endereço HTTPS e selecionar **Adicionar à tela inicial / Instalar app** quando aparecer. O botão depende do navegador e dos critérios da PWA.
6. A execução automática programada tenta coletar por volta das 7h11 de São Paulo (horário padrão UTC−3), mas o GitHub **não garante pontualidade**. Verificar a aba Actions se a coleta não acontecer.

**Limitação jurídica:** GitHub Pages gratuito não pode ser usado para hospedar um serviço comercial SaaS. Este piloto deve permanecer pessoal/experimental. A EBC distingue reprodução jornalística com atribuição de usos comerciais que exigem consulta ao setor de licenciamento. Usar RSS como fonte de títulos não é autorização geral para reutilizar o conteúdo completo.

## Regras básicas de confiança

- Sem data verificável ou link HTTP(S), o item não entra.
- O sistema não inventa a quantidade que falta em uma categoria.
- Nada aparece como edição de hoje se a coleta falhar e a última edição for anterior.
- O RSS aponta o link da fonte. O título e a data do feed não equivalem a validação independente do fato.
- Nunca inserir chaves de API ou senhas nos arquivos do repositório público.

## Fontes oficiais / leitura

- Índice RSS Agência Brasil: https://agenciabrasil.ebc.com.br/feed/
- Política de reprodução: https://agenciabrasil.ebc.com.br/sobre
- Agendamentos do GitHub Actions: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- Limites GitHub Pages: https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits

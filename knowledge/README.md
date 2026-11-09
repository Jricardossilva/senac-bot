# Base de conhecimento institucional do SENAC BOT

Conhecimento sobre o **Senac Brasil**, o **Senac Paraíba** e o **CEP João Pessoa (CEP-JP)**, organizado em arquivos JSON, consultável e atualizável **sem mudar a lógica da aplicação**. O assistente consulta esta base **antes** de responder qualquer pergunta institucional; o Gemini só organiza e explica o que a base entrega.

## Estrutura

```
knowledge/
  permanent.json     Informações permanentes (história, missão, modelo pedagógico, tipos de curso, números)
  units.json         Unidades (CEP-JP, CENDEGE, Gastronomia e Hotelaria, Tadros, Dom Ulrico, Zona Sul, Móveis, CG, Cajazeiras, Patos)
  courses.json       Cursos e programação (dados voláteis, com validade curta)
  programs.json      Programas institucionais (PSG, aprendizagem, Banco de Oportunidades, diversidade)
  social.json        Ações sociais, educação ambiental (4Rs), acessibilidade
  empresas.json      Senac Empresas e atendimento corporativo
  news_events.json   Notícias e eventos (fatos datados, todos com validade)
  faq.json           Canais oficiais, orientações e conteúdo educativo geral do projeto
  sources.json       Registro das fontes oficiais (só domínios do Senac, HTTPS) e política de atualidade
  aliases.json       Aliases de unidades, sinônimos, palavras de busca (editável)
  pending.json       Pendências: o que NÃO foi confirmado em fonte oficial
  state.json         (gerado) resultado da última consulta às fontes: datas, falhas, mudanças
  snapshots/         (gerado) última versão válida de cada página consultada
```

Código: `backend/knowledge/` (carregamento e validação, busca, composição das respostas, atualizador). Integração: `backend/ai/service.py`.

## Campos de cada entrada

| Campo | Função |
|---|---|
| `id`, `title` | Identificação única e título |
| `content` | Texto que pode ser **falado** (até 90 palavras; só fatos da fonte) |
| `category` | `permanent`, `units`, `courses`, `programs`, `social`, `empresas`, `news_events`, `faq` (o arquivo deve corresponder) |
| `level` | `brasil`, `paraiba` ou `cep-jp` |
| `unit` | Chave da unidade (`CEP-JP`, `CENDEGE`...) ou `null` quando é geral. **Informação de uma unidade nunca é atribuída a outra** |
| `kind` | `institutional` (exige fonte oficial), `guidance` (orientação com fonte) ou `general` (conteúdo educativo do projeto, sem URL) |
| `keywords`, `questions` | Termos e perguntas-exemplo que guiam a busca |
| `source_ids` | Fontes do `sources.json` (nome e URL oficial vêm de lá) |
| `consulted_at` | Data em que a informação foi lida na fonte (AAAA-MM-DD) |
| `valid_until` | Data de validade (obrigatória para notícias, eventos e dados voláteis) |
| `freshness` | `permanent` (revisão a cada 365 dias), `periodic` (120), `volatile` (30) |
| `status` | `verified`, `review` (divergência ou dúvida) ou `pending` (sem confirmação) |
| `short` | Forma curta para falar (ex.: canais oficiais) |
| `unit_note` | Aviso de escopo: dado geral que não pode ser atribuído a uma unidade |
| `notes` | Observações para o revisor (divergências entre páginas etc.); não são lidas ao visitante |

**Situação efetiva** (calculada na hora): `pending` > `stale` (passou da validade ou da idade máxima) > `review` (status `review` ou a página oficial mudou sem revisão) > `verified`. O assistente usa isso: informação vencida ou a confirmar sai com aviso e com o canal oficial.

## Fontes e confiabilidade

Somente páginas **oficiais** do Senac (`senac.br` e subdomínios): Senac Brasil, Senac PB, Senac Empresas. Nada de blogs, redes sociais de terceiros ou fontes não verificadas. Páginas inacessíveis ou sem o dado viram **pendência** em `pending.json`, nunca texto inventado. O conteúdo foi extraído das páginas em 07/11/2026; divergências entre páginas oficiais (por exemplo, o endereço da Escola de Gastronomia e Hotelaria) ficam como `review` com as duas versões nas `notes`.

## Como o assistente usa a base

1. Respostas locais curtas (saudações, "O que é o Senac?"...) saem direto do texto da base.
2. Demais perguntas passam pela **busca** (BM25 com sinônimos, aliases de unidade e checagem de cobertura da pergunta).
3. **Com dados confiáveis:** o Gemini recebe só as entradas encontradas (com âmbito, data, situação e fonte) e a instrução de usar somente elas. Se a resposta trouxer números que não estão nesses dados (telefone, ano, valor), ela é **descartada** e vale o texto da base. Sem Gemini ou com a IA fora do ar, responde-se direto com o texto da base.
4. **Pergunta sobre o Senac sem dados:** "Não tenho essa informação confirmada" + canal oficial. O Gemini nem é chamado.
5. **Pergunta geral** (ex.: ciência): Gemini sem contexto institucional.
6. **Empresas:** quem fala como empresa, empresário, colaboradores ou sindicato recebe a apresentação do Senac Empresas, sem valores nem propostas.
7. **Unidades:** se a pergunta cita uma unidade, entradas de outras unidades são excluídas; dados gerais saem com o aviso de que não confirmam que valem para aquela unidade.

## Catálogo de ofertas (`offers.json`)
Usado pela orientação para cursos (`backend/guidance`). Cada oferta é um fato público citado por uma página oficial:

| Campo | Significado |
|---|---|
| `id`, `kind` | identificador; `curso` (curso citado), `area` (área que a unidade confirma) ou `ead` (Senac EAD em geral) |
| `unit` | chave da unidade em `aliases.json` quando a página **confirma** a unidade; `null` quando só diz que o Senac Paraíba tem o curso; `"EAD"` para educação a distância |
| `phrase`, `pitch` | frase falável (quem/onde) e uma frase de por que pode interessar (até 30 e 32 palavras); sem preço, carga horária, data, horário, vagas ou requisitos |
| `keywords`, `refine` | assuntos que ativam a oferta; `refine` ajusta quando o visitante detalha o objetivo |
| `source_ids`, `evidence` | fontes oficiais e trechos literais da página, conferidos por `python -m backend.knowledge.verify` e pelos testes |
| `consulted_at`, `valid_until`, `freshness`, `status` | mesmas regras de validade das entradas; oferta vencida ganha o aviso "pode estar desatualizada", `pending` nunca é recomendada |

Prioridade da recomendação: `unit = "CEP-JP"` (nível 1), demais unidades e ofertas sem unidade informada (nível 2; unidade confirmada vem antes), `EAD` (nível 3). **Só adicione uma oferta do CEP-JP quando uma página oficial a citar**; enquanto isso, o robô informa que a programação do CEP-JP não está confirmada. Áreas amplas (ex.: tecnologia) podem ter `clarify` em `areas`: a pergunta de objetivo antes de recomendar.

## Extração do portal de cursos técnicos (`extractions/`)
`extractions/pb-programacao-cursos.json` guarda o que foi lido da fonte **Cursos Técnicos — Senac Paraíba** (URL, data da consulta, `next_review`, estrutura dos filtros, turmas normalizadas, registros e resolução das pendências). Cada registro: `id`, `kind`, `title`, `content`, `category`, `source_id`, `consulted_at`, `next_review`, `status` (`found`, `confirmed`, `awaiting_validation`, `divergent`, `stale`, `rejected`), `pending_ids`, `approved_by`, `volatile`, `speakable`, `note`, `update_proposal`. Regras: nada é aprovado sem o operador; valores e vagas são `speakable: false`; o arquivo nunca contém credenciais (`fields_discarded` lista só os NOMES dos campos descartados). Para atualizar: cartão Base de Conhecimento > **Consultar fonte** (ou `python -m backend.knowledge.portal [--force]`).

## Atualização

| Tipo de dado | Frequência recomendada |
|---|---|
| Permanente (história, missão, modelo pedagógico) | a cada 6 a 12 meses |
| Periódico (unidades, programas, ações sociais, Senac Empresas) | a cada 2 a 3 meses |
| Volátil (cursos, programação, notícias, PSG, eventos) | semanal, e **antes de cada evento** |

```powershell
powershell -File scripts\atualizar-conhecimento.ps1            # consulta as fontes oficiais e atualiza state.json
powershell -File scripts\atualizar-conhecimento.ps1 -Report    # o que está vencido, a confirmar, pendente e a saúde das fontes
powershell -File scripts\atualizar-conhecimento.ps1 -Only pb-psg
powershell -File scripts\atualizar-conhecimento.ps1 -Ack pb-unidades   # depois de revisar uma mudança
```

O atualizador: só acessa as páginas do `sources.json` (HTTPS, domínios oficiais); respeita o `robots.txt` (sem verificação possível, não acessa); identifica-se com um User-Agent próprio; espera 2,5 s entre requisições; nunca acessa áreas autenticadas; valida tamanho mínimo e marcadores esperados de cada página; **preserva a última versão válida** quando uma consulta falha; registra data, falhas e mudanças; e marca como **"a confirmar"** as entradas ligadas a uma página oficial que mudou, até a revisão (`-Ack`).

**Limite deliberado:** o atualizador detecta mudanças, mas **não reescreve o conteúdo curado**. Páginas oficiais mudam de formato; extrair fatos sem revisão poderia publicar um dado errado. Fluxo: rodar o atualizador -> ver as fontes marcadas -> conferir a página oficial -> editar o JSON (conteúdo, `consulted_at`, `valid_until`) -> `-Ack`. A programação de cursos por unidade é carregada por JavaScript e não pode ser lida automaticamente (veja `pending.json`).

No painel do operador, o cartão **Base de conhecimento** mostra contagens, fontes alteradas e pendências, e **Verificar sistema** avisa quando há informação central vencida.

## Como adicionar ou corrigir uma informação

1. Confirme a informação em página **oficial** e registre a fonte em `sources.json`, se ainda não estiver lá.
2. Edite o arquivo da categoria: `content` curto e falável, `source_ids`, `consulted_at` (hoje), `valid_until` quando o dado muda, `status`, `unit` se for de uma unidade.
3. Rode `.\.venv\Scripts\python.exe -m pytest tests\test_knowledge_store.py tests\test_knowledge_search.py`. A validação recusa entrada sem fonte oficial, data inválida, id duplicado, unidade desconhecida ou texto longo demais.
4. Sem confirmação oficial? Não crie a entrada: registre em `pending.json`.

Veja `EXEMPLOS.md` para perguntas e respostas reais.

# SENAC BOT

Robô virtual (depois físico, LEGO SPIKE Prime) que conversa com visitantes, responde por voz e simula movimentos.

## Ambiente
Windows 11, PowerShell 5.1, Python 3.11+ (testado com 3.14), Chrome/Edge. Sem Docker, sem Node/npm. Frontend em HTML/CSS/JS/SVG puros.

## Arquitetura
Módulos separados:
- **Interface** (frontend): HTML/CSS/JS/SVG.
- **Backend**: FastAPI + Uvicorn + API HTTP.
- **IA**: Google Gen AI SDK (`google-genai`), apenas no backend.
- **Reconhecimento de voz / Síntese de voz**.
- **Controlador do robô**: único ponto que executa ações.
- **Abstração de hardware**: interface comum implementada pelo **simulador** e pela **integração física** (Bleak/BLE, futuro).

A IA nunca envia comandos aos motores. Toda ação passa pelo controlador, pela lista de comandos permitidos e pelas regras de segurança.

## Estrutura de diretórios
```
senac-bot/
  backend/        main.py (rotas FastAPI), config.py, state.py (estados), events.py (eventos),
                  errors.py (tratamento centralizado)
    ai/           base.py (interface AIProvider), gemini.py (provedor google-genai), service.py (fluxo híbrido),
                  local_answers.py, knowledge.py, persona.py, context.py (contexto por sessão, só em memória)
    knowledge/    base.py (KnowledgeBase), store.py (carga/validação/atualidade), search.py (busca BM25 + unidades), compose.py (contexto, resposta extrativa, checagem de números), updater.py + update.py (atualização das fontes oficiais)
    eventkb/      models.py, store.py (persistência JSON por evento), extract.py (blocos literais), research.py (pesquisa/atualização), manager.py (ativação, validação, trabalhos), knowledge.py (busca do evento ativo), discovery.py, seed.py (Robótica 2026)
    policy/       inbound.py (política de entrada: sigilo e manipulação), outbound.py (política de saída, aplicada a TODA resposta), messages.py (textos fixos)
    guidance/     engine.py (orientação de cursos: CEP-JP > outras unidades do Senac PB > Senac EAD), session.py (estado por sessão, só em memória)
    robot/        controller.py (único ponto de execução, regras de segurança), actions.py (lista de comandos permitidos)
    hardware/     base.py (interface comum), simulator.py (simulador), physical.py (físico: ainda indisponível)
  frontend/       index.html, app.css, app.js (módulo principal), speech.js (voz), conversation.js (máquina de estados da conversa por voz), diagnostics.js (diagnóstico de áudio), demo.js (roteiro da demonstração)
  events/         dados dos eventos (uma pasta por evento: event.json, sources.json, knowledge.json, history.json, snapshots/)
  knowledge/      base de conhecimento institucional (JSON por categoria, offers.json = catálogo de ofertas da orientação de cursos, sources.json, aliases.json, pending.json, fact_checks.json, state.json, snapshots/)
  tests/          testes pytest; e2e/ = testes de interface no Edge (manuais, ver docs/RELATORIO_TESTES.md)
  docs/           AUDIO_WINDOWS.md (configuração de áudio), RELATORIO_TESTES.md
  scripts/        setup.ps1, run.ps1 (iniciar.bat na raiz)
  requirements.txt            dependências da aplicação
  requirements-hardware.txt   bleak (hardware futuro, instalação manual)
  .env.example    modelo de configuração
  CLAUDE.md, README.md
```

## Comandos PowerShell
```powershell
powershell -File scripts\setup.ps1   # instalação (cria .venv, instala dependências)
powershell -File scripts\run.ps1     # execução (http://localhost:8000; instala sozinho na 1ª vez; -NoBrowser, -Port)
iniciar.bat                          # dois cliques: o mesmo que run.ps1
.\.venv\Scripts\python.exe -m pytest # testes
```
Os scripts chamam `.venv\Scripts\python.exe` diretamente; não é preciso ativar o ambiente. Nunca instalar dependências globalmente.

## Configuração
Variáveis em `.env` (copiado de `.env.example` pelo setup): `SENAC_HOST`, `SENAC_PORT`, `SENAC_LOG_LEVEL`, `APP_ENV`, `ROBOT_MODE` (somente `simulation`), `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_TIMEOUT_SECONDS`, `GEMINI_MAX_RETRIES`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_CHARSET`, `DB_SSL`.
Eventos: com `DB_*` preenchidas, o Gerenciador de Eventos grava no MySQL (Hostinger; tabela `senacbot_event_docs`, criada sozinha) via `backend/eventkb/storage.py` (`MySQLStorage`); sem elas, usa arquivos em `events/` (`FileStorage`). `scripts/migrar_eventos_mysql.py` copia `events/` para o banco. A base institucional (`knowledge/`) continua em JSON versionado no repositório. A extração do portal de cursos (turmas, registros e decisões do operador) usa o MESMO `MySQLStorage` com a chave `PORTAL_KEY` (`_portal/pb-programacao-cursos.json`, que nunca aparece como evento): `PortalKnowledge.load()` lê o banco e cai no arquivo versionado (semente) se o banco estiver vazio/fora; `save()` grava no banco e, se falhar, só em arquivo (o chat segue com dado novo) e `decide()` levanta `PortalStorageError` (HTTP 503). Sem `DB_*`, tudo em arquivo.

### Gemini
Chave obtida no Google AI Studio e colocada em `GEMINI_API_KEY` no `.env`. Fica somente no backend; nunca no frontend nem no repositório. Sem chave ou sem internet, o robô usa respostas programadas.
Sem chave, a aplicação inicia normalmente, `/health` informa `gemini_status: not_configured` e a interface avisa que o Gemini não está configurado.
Fluxo híbrido do chat (`/chat`): resposta local (perguntas curtas conhecidas) -> Gemini -> contingência local se a API falhar. A origem (`local`, `gemini`, `fallback`) aparece em cada mensagem. Status possíveis: `not_configured`, `configured`, `available`, `invalid_key`, `rate_limited`, `unavailable`, `model_unavailable`. O operador pode verificar a conexão em "Verificar Gemini" (`/api/ai/check`).
Modelos Gemini são descontinuados com frequência: confira a lista oficial (ai.google.dev/gemini-api/docs/models) e ajuste `GEMINI_MODEL`. Contexto: últimas 6 trocas por sessão, em memória, apagado ao encerrar a sessão ou acionar a emergência. E-mails e números longos são removidos antes do envio ao Gemini.

### Interface e simulador
`/` serve quatro ambientes: visitante, operador, simulador e diagnóstico de áudio. O backend expõe `/api/status`, `/ws/status` (WebSocket com o estado em tempo real; a página cai para polling HTTP se o socket fechar), `/api/session/start|stop`, `/api/emergency`, `/api/simulator/action`, `/api/simulator/sensors`, `/api/ai/check`, `/api/preflight` (internet, Gemini, hardware, emergência), `/api/hardware/mode`, `/api/demo/start|stop` e `/chat`.
Modo evento: o operador usa "Verificar sistema" (backend + áudio do navegador), alterna simulador/físico e inicia a demonstração (roteiro em `frontend/demo.js`, falas locais; só as perguntas usam o Gemini, com contingência). `ROBOT_MODE=physical` ainda não existe: `PhysicalHardware.connect()` falha com mensagem clara e o simulador permanece ativo. Emergência, encerrar sessão ou encerrar demonstração interrompem o roteiro.
Toda ação do robô (8 expressões e 12 movimentos, definidos em `backend/robot/actions.py`) passa por `RobotController.execute()`: lista permitida, parada de emergência, conexão e obstáculo (< 20 cm bloqueia avanço e para as rodas). Gestos voltam ao neutro após 3 s; rodas persistem até `stop`. Sensores simulados (distância, conexão) são editáveis só no simulador. O `/chat` informa a intenção da mensagem e o controlador decide a reação (por exemplo, cumprimentar). O simulador é visual e não controla hardware físico; a integração com o LEGO SPIKE Prime ainda não existe e só deve ser feita após o inventário real de peças.

### Base de conhecimento institucional
Conhecimento sobre Senac Brasil, Senac PB e CEP-JP fica em `knowledge/*.json` (NÃO no prompt do Gemini). Cada entrada tem fonte oficial (`source_ids` -> `sources.json`, só domínios `senac.br`), `consulted_at`, `valid_until`, `freshness`, `status` e, quando aplicável, `unit`. Regras: nunca inventar nem presumir; o que não foi confirmado vai para `pending.json`; informação de uma unidade jamais é atribuída a outra; notícias/eventos são fatos datados com validade. Fluxo do chat (`backend/ai/service.py`): resposta local -> busca na base -> (com dados) Gemini recebe só o contexto recuperado e a resposta é descartada se trouxer números fora dele, ou resposta direta da base; (sem dados, mas pergunta institucional) "não tenho confirmação" + canal oficial; pergunta geral -> Gemini sem contexto. Visitante que fala como empresa recebe o Senac Empresas. Atualização: `scripts\atualizar-conhecimento.ps1` (robots.txt, domínios oficiais, validação, preserva a última versão válida, marca mudanças como "a confirmar" até `-Ack`); o atualizador não reescreve o conteúdo curado. Ao editar dados, rode `tests/test_knowledge_*.py`. Detalhes em `knowledge/README.md`.

### Portal oficial de cursos técnicos (fonte `pb-programacao-cursos`)
`backend/knowledge/portal.py`: lê a página e a listagem pública de turmas (`get-turmas.php`, a mesma chamada da página) pelo `PoliteFetcher` (robots.txt, domínio oficial, intervalo), copia SÓ campos de uma lista permitida (credenciais de pagamento que o endpoint devolve são descartadas e nunca gravadas ou exibidas) e grava `knowledge/extractions/pb-programacao-cursos.json` (registros com origem, data da consulta, situação e próxima revisão). Nada é aprovado automaticamente: apenas cruzamento com outra página oficial já registrada vira "Confirmada"; registros aprovados pelo operador nunca são sobrescritos (nova versão = proposta); rejeitados não voltam; falha de rede mantém tudo. `RESOLUTION_RULES` relaciona registros às pendências de `pending.json` (nunca as apaga): `awaiting_validation`, `divergent`, `unresolved`, `resolved` (só após o operador confirmar dado estável), `failed`, `not_related`, `not_consulted`. Valores, vagas, datas e horários SÃO falados (`spoken_turma`/`PortalLookup.describe`), sempre com a data da consulta e a ressalva de que mudam. A extração roda todo dia (`refresh_if_stale`: inicialização via `scripts/atualizar-cursos.ps1` chamado por `run.ps1`, agendador em segundo plano de `main.py`, tarefa opcional `scripts/agendar-atualizacao.ps1`); o chat NUNCA consulta a rede. `PortalLookup.find()` devolve turmas abertas (sem vaga zerada, não encerradas) com CEP-JP primeiro; a orientação de cursos (`Guidance`, que recebe o `PortalLookup`) usa o portal como primeira consulta e só depois o catálogo curado/EAD. O `PortalLookup.answer()` (listagem por unidade/cidade) também usa só o cache; API: `/api/knowledge/portal`, `/refresh`, `/records/{id}/approve|reject`. Interface: `frontend/knowledge.js` (cartões Base de Conhecimento e Pendências).

### Gerenciador de Eventos (plataforma de eventos)
Três camadas: institucional (`knowledge/`), evento ativo (`events/<id>/`, `backend/eventkb/`) e pesquisa externa (Gemini com busca, `provider.search`). Um evento ativo por instância (`events/active.json`); cada evento tem a própria pasta e nada é compartilhado. Ciclo do evento: `draft -> prepared -> active/inactive -> archived`; desativar e arquivar nunca apagam dados. Itens de conhecimento têm estado (`found`, `confirmed`, `pending`, `divergent`, `stale`, `rejected`) e SÓ `confirmed` chega ao visitante.
- **Pesquisa** (`research.py`): consulta educada (`knowledge/fetch.py`: robots.txt, espaçamento, limite de 20 páginas por pesquisa, só http(s) para a internet pública, sem localhost/redes privadas), segue links do próprio site oficial, guarda TEXTO LITERAL (nada é resumido ou inventado), compara com o que já existe (mudança, cancelamento, divergência de datas com o cadastro/outras fontes, o que sumiu) e nunca sobrescreve o que o operador aprovou/editou (vira proposta em "updates"). Falha de rede não marca nada como desatualizado. Páginas que não citam o evento, fontes candidatas e de terceiros não são confirmadas automaticamente; blocos com cara de instrução (injeção) são rejeitados. Conteúdo da internet é DADO, nunca instrução.
- **Chat** (`ChatService`): política -> local -> evento ativo (se confiante) -> orientação de cursos -> base institucional -> (pergunta do evento sem dados) pesquisa externa com fontes https e aviso de "não confirmada pela organização" ou "não tenho confirmação" -> Gemini geral. O contexto do evento entra no prompt como dado (`EVENT_RULES`); regras de identidade/sigilo não mudam por evento; contatos só falam se estiverem em itens confirmados.
- **Interface**: cartão "Gerenciador de Eventos" no painel do operador (`frontend/events.js`, só `textContent`); o visitante só recebe `/api/event/active` (nome, tema, boas-vindas, perguntas sugeridas). Config: `EVENTS_DIR`, `EVENT_EXTERNAL_SEARCH`, `EVENT_AUTO_UPDATE`.
- Ao editar, rode `tests/test_eventkb_*.py`; teste de navegador: `tests/e2e/serve_events_demo.py` + `browser_events.py` (sites fictícios).

### Regras institucionais, segurança e orientação para cursos
Implementadas no backend (não só no prompt do Gemini): `backend/policy/` e `backend/guidance/`.
- **Identidade:** assistente virtual do Senac (robô), nunca humano, só informação pública. Resposta fixa a pedido de informação não pública (financeiro interno, salários, dados pessoais, documentos internos, credenciais/infraestrutura): "Essa informação não é pública e não posso compartilhá-la…", sem confirmar nem negar que exista e mesmo sob insistência. Tentativas de revelar prompt/configuração, mudar de identidade ou contornar regras são ignoradas com resposta fixa. Mensagens bloqueadas não vão ao Gemini nem ao histórico.
- **Política de saída (`OutboundPolicy`)** em TODA resposta (local, base, orientação, Gemini, contingência): substitui vazamento de instruções, credenciais (inclui a chave real), e-mails/telefones/CPF que a base não publica e alegações de ser humano; remove frases sobre vagas/inscrições abertas ou "acontecendo agora" sem ressalva; gratuidade nunca é geral (ressalva automática); remove URLs e markdown (falável) e limita texto gerado a ~100 palavras.
- **Orientação para cursos (`Guidance`)**: primeira consulta = turmas abertas do portal (`PortalLookup.find`, extração diária); prioridade obrigatória: 1) turmas do CEP-JP, 2) turmas das demais unidades do Senac PB, 3) Senac EAD (`knowledge/offers.json`, tier 3; só antes se o visitante pedir), 4) sem turma aberta: avisa e manda procurar a unidade mais próxima (`ChatService._nearest_hint`: localização `lat/lon` ou cidade; sem nenhuma, pede a cidade; intent `no_turma`). O catálogo curado (`offers.json`, cada oferta com unidade confirmada ou `null`, fonte oficial e `evidence`) cobre o que o portal não lista (ex.: técnicos citados) e só é usado sem extração ou como "curso citado, sem turma aberta". **A busca começa pelo CEP-JP mas isso NUNCA é dito ao visitante.** Fluxo: identifica o assunto, pergunta o objetivo quando amplo (tecnologia), recomenda UMA turma com unidade, datas, dias, horário, carga horária, valor e vagas + data da consulta e ressalva; "valor?/vaga?/horário?" repete os dados; "sim"/"outra opção" traz a próxima turma (nunca repete); "não" encerra sem insistir. Ids de turma em `offer_ids`: `turma-N`. Gratuidade: Programa Senac de Gratuidade com ressalva (nem todo curso é gratuito). Empresas vão ao Senac Empresas; ações sociais à base social; perguntas sem relação com cursos são respondidas primeiro, com no máximo uma sugestão pertinente (intervalo mínimo de 3 mensagens, sem repetir oferta, nunca após desinteresse).
- **Contexto da conversa:** o serviço lembra, só em memória e por sessão, a unidade e o assunto da conversa para perguntas curtas de acompanhamento ("E o telefone?", "Tem curso lá?"); "sim/não" soltos e a resposta padrão de "não sei" têm variações; pedidos de preço, horário, vaga ou carga horária recebem a entrada `faq-valores-vagas-datas`.
- **Links:** `/chat` devolve `links` (rótulo + URL oficial `https`) que a interface mostra como botões abaixo da mensagem (abrem em outra aba; nunca falados em voz alta).
- Textos de orientação com até ~70 palavras e uma pergunta de continuidade. Ao editar `offers.json`, rode `tests/test_guidance.py` e `python -m backend.knowledge.verify`.

### Identidade visual
Tema claro institucional (azul, branco, laranja) em `frontend/app.css`. O avatar é um único SVG (`<template id="avatar-template">` em `index.html`), montado pelo JS no visitante e no simulador; as classes `head`, `eyes`, `eye`, `mouth`, `arm-*`, `wheel`, `sensor-dot` etc. e as coordenadas do rosto são usadas pelas animações de expressão/movimento: mudar a geometria exige ajustar os `d: path(...)` do CSS. A tela do visitante não exibe informação técnica da IA (a origem das respostas só aparece com a opção do operador). Os logotipos oficiais estão em `frontend/brand/` e nunca devem ser redesenhados, recoloridos ou distorcidos (altura fixa + largura automática; a versão branca é só o filtro CSS `brightness(0) invert(1)`).

### Áudio
Microfone integrado do notebook, acessado pelo navegador (Chrome/Edge) com permissão do usuário. A página deve rodar em `localhost`. O áudio nunca é gravado nem armazenado. Reconhecimento: Web Speech API pt-BR (exige internet no Chrome/Edge). **A conversa do visitante é só por voz** e controlada por uma máquina de estados (`frontend/conversation.js`, sem acesso ao DOM, com dependências injetadas): INICIAR CONVERSA -> pede permissão -> abre a sessão -> ouve -> envia o texto ao `/chat` -> fala a resposta -> volta a ouvir sozinho; ENCERRAR CONVERSA, inatividade (2 min), emergência, sessão encerrada pelo operador ou sair da tela do visitante abortam o reconhecimento e liberam o microfone. Regras: o reconhecimento só roda no estado "ouvindo" (nunca durante a fala do robô), descarta resultados fora da escuta, frases repetidas e frases parecidas com a resposta do robô, e há vigia contra laços de reinício e contra a síntese que não termina. Falhas definitivas (voz/microfone/permissão/conexão) levam ao estado "indisponível" com mensagem clara; **não existe campo de texto na tela do visitante** (o operador tem o cartão "Testar respostas por texto"). Síntese: SpeechSynthesis com voz pt-BR e botão Interromper fala. A aba Diagnóstico testa permissão, dispositivo, nível, reconhecimento e voz. Passo a passo das permissões do Windows e decisão sobre Vosk/faster-whisper: `docs/AUDIO_WINDOWS.md`.

## Regras de segurança e permanentes
- Chaves exclusivamente no backend; `.env` fora do git.
- Nunca armazenar áudio dos visitantes; sem reconhecimento facial.
- Não armazenar conversas pessoais desnecessariamente.
- Respostas programadas funcionam sem internet.
- Comandos do robô só pela lista permitida, via controlador.
- Não simular integração física como se fosse real.
- Sem botões sem função; sem funcionalidades extras desnecessárias.
- Código modular, tipado, com tratamento de exceções e logs claros.
- Nenhuma funcionalidade está concluída sem testes.

## Regras de trabalho
Inspecionar antes de alterar; testar após cada etapa; corrigir erros antes de avançar; consultar documentação oficial; informar arquivos criados e modificados.

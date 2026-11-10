# SENAC BOT — Tecnologia que conversa com você

Robô virtual educacional para a **Robótica 2026 (Senac PB, 23 a 29 de novembro de 2026; visitação de 25 a 29)**. Ele conversa por voz com os visitantes, responde com respostas locais e com o Gemini, se expressa e se movimenta em um simulador na tela. A integração com o LEGO Education SPIKE Prime (modo físico) ainda **não** está disponível.

## Requisitos
- Windows 11, PowerShell, Python 3.11 ou superior (testado com 3.14).
- Google Chrome ou Microsoft Edge (voz e reconhecimento de fala).
- Internet é opcional: sem ela o robô usa respostas locais.

## Instalação
Opção simples: dê dois cliques em **`iniciar.bat`**. Na primeira vez ele cria o ambiente (`.venv`), instala as dependências e abre o navegador.

Passo a passo manual:
```powershell
powershell -File scripts\setup.ps1   # cria .venv, instala requirements.txt, verifica e cria o .env
```
Nada é instalado globalmente; os scripts usam `.venv\Scripts\python.exe` diretamente.

## Configuração (`.env`)
O `setup` cria o `.env` a partir do `.env.example`. Variáveis:

| Variável | Padrão | Função |
|---|---|---|
| `GEMINI_API_KEY` | vazio | Chave do Gemini. Vazia = somente respostas locais. |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Modelo do Gemini. Modelos antigos são descontinuados; confira a [lista oficial](https://ai.google.dev/gemini-api/docs/models). |
| `GEMINI_TIMEOUT_SECONDS` / `GEMINI_MAX_RETRIES` | `10` / `1` | Limite de espera e de novas tentativas. |
| `ROBOT_MODE` | `simulation` | `simulation` ou `physical` (o físico ainda não existe: cai no simulador com aviso). |
| `APP_ENV` | `development` | Nome do ambiente. |
| `KNOWLEDGE_DIR` | `knowledge` | Pasta da base de conhecimento institucional (JSON). |
| `EVENTS_DIR` | `events` | Pasta do Gerenciador de Eventos (uma subpasta por evento). |
| `EVENT_EXTERNAL_SEARCH` | `true` | Permite a pesquisa externa (Gemini com busca) para perguntas do evento ativo sem resposta nas bases. |
| `EVENT_AUTO_UPDATE` | `true` | Permite a atualização programada dos eventos que a configuraram. |
| `SENAC_HOST` / `SENAC_PORT` / `SENAC_LOG_LEVEL` | `127.0.0.1` / `8000` / `INFO` | Endereço, porta e nível de log. |

### Ativar o Gemini
1. Acesse https://aistudio.google.com/apikey e crie uma chave.
2. Cole em `GEMINI_API_KEY=` no `.env` (**nunca** em arquivos Python ou JavaScript; o `.env` não vai para o Git).
3. Escolha um modelo disponível para a sua chave em `GEMINI_MODEL` (o padrão costuma servir).
4. Reinicie e, no painel do operador, clique em **Verificar sistema**. O Gemini deve aparecer como "Disponível".
5. Teste uma pergunta aberta, por exemplo "Como um robô desvia de obstáculos?". A origem da resposta aparece em cada mensagem.

Sem chave, sem cota ou sem internet, o robô continua funcionando com respostas locais.

## Execução
```powershell
powershell -File scripts\run.ps1                 # abre http://localhost:8000 no navegador
powershell -File scripts\run.ps1 -NoBrowser      # sem abrir o navegador
powershell -File scripts\run.ps1 -Port 8100      # outra porta
```
Para encerrar: `Ctrl+C` na janela do PowerShell (ou feche a janela do `iniciar.bat`).

Testes: `.\.venv\Scripts\python.exe -m pytest`

Versão em produção: no Render, `https://<seu-servico>.onrender.com/health` mostra `"versao"` com os 7 primeiros caracteres do commit publicado (compare com o último commit do GitHub). Fora do Render o campo fica vazio.

## Como operar no evento
Use **uma única janela do navegador** (por exemplo em tela cheia no notebook) e alterne entre as abas.

**Antes de abrir ao público**
1. Inicie o programa (`iniciar.bat`) e abra a aba **Operador**.
2. Clique em **Verificar sistema**. A lista mostra, com mensagem e ação sugerida, o estado de: internet, Gemini, hardware, parada de emergência, microfone, reconhecimento de voz e voz sintetizada. Itens em laranja são avisos (o robô usa a contingência local); itens em vermelho impedem a demonstração.
3. Na aba **Diagnóstico**, teste o microfone e a voz (veja [docs/AUDIO_WINDOWS.md](docs/AUDIO_WINDOWS.md)). Libere o microfone quando o navegador perguntar.
4. Volte para **Visitante** e, se quiser, use o botão de tela cheia no topo.

**Durante o atendimento**
- **Iniciar demonstração**: o robô se cumprimenta, apresenta-se, explica o que faz, pergunta como pode ajudar e abre uma janela de 30 s para perguntas (o tempo reinicia a cada pergunta; use **Continuar demonstração** para seguir). Depois propõe um desafio, mostra expressões e movimentos e se despede. Tudo funciona sem internet; só as perguntas abertas usam o Gemini e, se ele falhar, respostas locais.
- **Encerrar demonstração** interrompe o roteiro e a fala a qualquer momento. **Iniciar/Encerrar sessão** controla o atendimento livre.
- **Parada de emergência** bloqueia todos os comandos do robô e o chat, encerra a demonstração e silencia a voz. Use **Liberar parada de emergência** para retomar.
- Em **Operador** o **Modo de hardware** alterna entre simulado e físico. Se o físico falhar (hoje, sempre), o simulador continua ativo e a mensagem explica o motivo; **Modo simulado** limpa o aviso.
- **Conversa do visitante (por voz):** o visitante toca em **INICIAR CONVERSA**, autoriza o microfone (só na primeira vez) e fala. O SENAC BOT responde falando e **volta a ouvir sozinho**: não é preciso tocar de novo a cada pergunta. **Interromper fala** corta a resposta, e **ENCERRAR CONVERSA** termina a sessão e libera o microfone a qualquer momento. Sem fala por 2 minutos a conversa se encerra sozinha. Não há campo de texto na tela do visitante.
- **Operador:** o cartão **Testar respostas por texto** (aba Operador) confere as respostas sem usar o microfone. Ele não aparece para o visitante.

## Solução de problemas
| Sintoma | O que fazer |
|---|---|
| `iniciar.bat` fecha rápido ou o Python não é encontrado | Instale o Python 3.11+ em python.org marcando "Add python.exe to PATH" e execute `scripts\setup.ps1`. |
| "A porta 8000 já está em uso" | O SENAC BOT já está aberto ou outro programa usa a porta. Feche-o ou mude `SENAC_PORT` no `.env`. |
| Falha ao instalar dependências | Verifique a internet e rode `scripts\setup.ps1` de novo; a mensagem do pip aparece na tela. |
| Gemini "Não configurado" | Preencha `GEMINI_API_KEY` no `.env` e reinicie. |
| Gemini "Chave inválida" | Gere outra chave em aistudio.google.com/apikey e atualize o `.env`. |
| Gemini "Limite atingido" | A cota gratuita acabou; aguarde a renovação ou troque `GEMINI_MODEL`. O robô usa respostas locais enquanto isso. |
| Gemini "Modelo indisponível" | O modelo foi descontinuado: escolha outro na lista oficial. |
| Respostas do Gemini muito lentas | Troque para um modelo "flash-lite" em `GEMINI_MODEL`. O padrão já é um deles. |
| "Sem internet" | Reconecte o Wi-Fi. O reconhecimento de voz do Chrome/Edge precisa de internet: sem ela a conversa por voz fica indisponível (a demonstração segue com falas locais). Use o teste de mensagem do operador para validar as respostas. |
| Visitante vê "microfone indisponível" ou "bloqueado" | Veja a mensagem: ela diz se o microfone está bloqueado, ausente, em uso por outro programa ou se o navegador não suporta voz. Siga [docs/AUDIO_WINDOWS.md](docs/AUDIO_WINDOWS.md) e toque em INICIAR CONVERSA de novo. |
| O robô responde ouvindo a própria voz | Use fones ou afaste o microfone do alto-falante; o sistema já ignora frases iguais à resposta e só ouve depois que o robô termina de falar. |
| Microfone não funciona | Siga [docs/AUDIO_WINDOWS.md](docs/AUDIO_WINDOWS.md): privacidade do Windows, permissão do navegador e acesso por `localhost`. |
| Robô não fala | Veja o volume do Windows/da aba, teste em **Diagnóstico > Testar voz**. Sem voz, a resposta fica na tela. |
| Modo físico indisponível | Esperado: o modo físico ainda não existe. Use o simulador. |
| Tela do robô "travada" após um erro | Clique em **Aguardar** no Simulador ou recarregue a página (F5). |

## Base de conhecimento institucional
O SENAC BOT conhece o **Senac Brasil, o Senac Paraíba e o CEP João Pessoa (CEP-JP)** por uma base estruturada em `knowledge/` (arquivos JSON por categoria, com fonte oficial, data de consulta, validade e status de cada informação). Antes de responder qualquer pergunta sobre o Senac o sistema consulta essa base; o Gemini só explica os dados encontrados, e sem dados o robô diz que não tem confirmação e indica o canal oficial.

- **O que há:** Senac Brasil, Senac PB, unidades de João Pessoa (CEP-JP, CENDEGE, Gastronomia e Hotelaria, Dom Ulrico, Zona Sul, Tadros), cursos e programação, PSG, aprendizagem, ações sociais e educação ambiental (4Rs), Senac Empresas, notícias e canais oficiais.
- **Programação de cursos (turmas abertas por unidade, com datas, horários, carga horária, valores e vagas):** vem do portal oficial de matrículas, lido **todos os dias** (veja abaixo). O robô fala esses dados, sempre com a data da consulta e a ressalva de que mudam.
- **O que ainda não há (pendências):** turmas de curso técnico, ensino superior, pós-graduação, PSG e Aprendizagem (o portal só lista turmas com matrícula aberta e, em 10/11/2026, não havia essas), calendário de ações sociais, horário de atendimento das unidades etc.; a lista completa está em `knowledge/pending.json`.
- **Conhecimento do robô:** é o conhecimento geral do próprio modelo **mais** tudo o que está na base do Senac e, quando há um evento ativo, o que foi cadastrado e pesquisado para o evento. A base do Senac sempre vence quando o assunto é o Senac.
- **Atualizar:** `powershell -File scripts\atualizar-conhecimento.ps1` consulta as fontes oficiais (respeitando o `robots.txt`), valida, preserva a última versão válida e marca o que mudou para revisão; `-Report` mostra o que está vencido ou pendente. Antes de cada evento, rode e revise.
- **Detalhes:** `knowledge/README.md` (estrutura, campos, política de fontes e atualização) e `knowledge/EXEMPLOS.md` (perguntas e respostas reais). O painel do operador tem o cartão **Base de conhecimento**.

## Fonte oficial de cursos técnicos (portal de matrículas)
A fonte **Cursos Técnicos — Senac Paraíba** (`https://pb.senac.br/matriculas/matricula/cursos-tecnicos/index.php`, categoria "Cursos e matrículas", Senac PB, fonte oficial) é lida pelo operador no cartão **Base de Conhecimento**: **Consultar fonte** lê a página (filtros de cidade, unidade, segmento, modalidade...) e a listagem de turmas que a própria página carrega, respeitando o `robots.txt`, com cache até a próxima revisão (7 dias) e intervalo mínimo entre consultas. O resultado fica em `knowledge/extractions/pb-programacao-cursos.json`, em registros com origem, data da consulta, situação (Encontrada, Confirmada, Aguardando validação, Divergente, Desatualizada, Rejeitada) e data da próxima revisão. **Nada é aprovado automaticamente** (só o operador confirma, e apenas endereços que coincidem com outra página oficial já registrada aparecem como "Confirmada" pelo cruzamento); versão nova de um registro aprovado vira proposta. Cada pendência de `knowledge/pending.json` relacionada à fonte mostra se há informação encontrada, se continua sem solução ou se está divergente; as pendências **não são apagadas**. Valores, vagas, datas e horários **são falados** pelo robô, sempre com a data da consulta e a ressalva de que mudam. O portal é lido **antes** das conversas (nunca durante, porque demora): o chat só usa essa última extração salva.

**Atualização diária (a extração roda em três momentos):**
1. **Toda vez que o robô é iniciado** (`iniciar.bat` / `scripts\run.ps1` chamam `scripts\atualizar-cursos.ps1`): consulta só se a última consulta não foi hoje.
2. **Em segundo plano**, enquanto o robô está aberto (checa a cada 5 minutos e baixa de novo se mudou o dia).
3. **Tarefa agendada do Windows (opcional)**, para ter a programação do dia mesmo com o robô fechado: `powershell -File scripts\agendar-atualizacao.ps1` (todo dia às 06:00; `-Hora 05:30` muda o horário; `-Remover` apaga a tarefa).

**Onde a programação fica salva:** com o MySQL configurado (`DB_*`, o mesmo banco dos eventos), a extração e as decisões do operador ficam no banco (tabela `senacbot_event_docs`, chave `_portal/pb-programacao-cursos.json`) e **sobrevivem a reinícios e deploys do Render**, cujo disco é apagado. Depois de uma "acordada" do Render o robô já abre com a programação do dia e não precisa consultar o portal de novo. O arquivo `knowledge/extractions/pb-programacao-cursos.json` do Git vira só a **semente**, usada enquanto o banco está vazio ou fora do ar. Sem `DB_*` (uso local), o arquivo é a única fonte, como antes. Se o banco cair na hora de gravar, a programação nova vale só até o próximo reinício e o painel avisa; decisões do operador (aprovar/rejeitar) falham com aviso em vez de fingir que gravaram.

Se a consulta falhar (sem internet, portal fora do ar), a última programação salva continua valendo, e o robô sempre diz a data em que ela foi consultada. Linha de comando: `python -m backend.knowledge.portal [--force | --if-stale]` ou `powershell -File scripts\atualizar-cursos.ps1 [-Force]`.

**Cobertura:** o portal só lista turmas com matrícula aberta (formação inicial e continuada, aperfeiçoamento, ações extensivas e programas socioculturais/socioprofissionais). Os filtros de nível técnico, superior, pós-graduação e PSG retornam vazio quando não há turma aberta; o robô não inventa essas turmas.

## Gerenciador de Eventos
O SENAC BOT é uma plataforma para eventos: o robô, o avatar, a voz e as regras de segurança são sempre os mesmos; o que muda é o **evento ativo**. O conhecimento fica em três camadas: (1) institucional do Senac (`knowledge/`, sempre disponível), (2) conhecimento do evento ativo (`events/<evento>/`, uma pasta por evento, sem mistura) e (3) pesquisa externa (Gemini com busca, só para perguntas do evento sem resposta nas camadas 1 e 2).

**Cadastrar e ativar um novo evento (sem mexer no código):**
1. Painel do operador > **Gerenciador de Eventos** > **NOVO EVENTO**. Obrigatórios: nome, área, descrição e datas de início e término. O restante (site oficial, programação, redes, local, palavras-chave...) pode ser informado depois.
2. **PESQUISAR E PREPARAR EVENTO**: o sistema consulta o site oficial informado (e os links dele para programação, visitação, perguntas frequentes etc.), respeitando o `robots.txt`, com intervalo entre requisições e limite de páginas. Sem site, tenta descobrir candidatos por pesquisa (que **nunca** são confirmados sozinhos); se nada for encontrado, informe fontes públicas em "Adicionar fonte".
3. Revise o conteúdo por categoria. Cada informação tem estado (Encontrada, Confirmada, Aguardando validação, Divergente, Desatualizada, Rejeitada), fonte e histórico. Trechos literais de fontes oficiais são confirmados automaticamente (regra desligável no cadastro); o resto aguarda você: **Aprovar**, **Editar** ou **Rejeitar**. Datas que divergem do cadastro ou entre fontes ficam como "Divergente".
4. **ATIVAR EVENTO**: a tela do visitante passa a mostrar o nome do evento, a boas-vindas e perguntas sugeridas, e o robô responde sobre o evento (só com informações confirmadas). Só um evento fica ativo; ativar outro desativa o anterior.
5. **ATUALIZAR BASE** repete a pesquisa: detecta mudança de horário, cancelamento, novidades e o que sumiu da fonte; o que você aprovou ou editou nunca é sobrescrito (uma versão nova vira proposta em "Atualizações"). A atualização programada (horas) é opcional por evento, no cadastro.
6. **DESATIVAR** volta à experiência institucional e **ARQUIVAR** guarda o evento; nada é apagado.

O primeiro evento cadastrado é a Robótica 2026 (datas e organização do projeto; sem programação inventada). Os dados ficam em `events/` (copie a pasta para levar os eventos a outro computador). O painel não aparece na tela do visitante.

## Regras institucionais e orientação para cursos
O SENAC BOT é um **assistente virtual do Senac Paraíba** (nunca se apresenta como pessoa) e só divulga informações públicas.

- **Sigilo:** pedidos de informação financeira interna, salários, dados pessoais, documentos internos, senhas ou detalhes de sistemas recebem sempre a mesma resposta ("Essa informação não é pública e não posso compartilhá-la…"), sem confirmar nem negar que a informação exista, mesmo que o visitante insista. Tentativas de ver o prompt, mudar a identidade do robô ou "ignorar as regras" também são recusadas. A política roda no backend, antes e depois de qualquer resposta (locais, da base e do Gemini).
- **Orientação para cursos:** o robô identifica o interesse do visitante e recomenda **uma turma por vez**, sempre começando pela programação do portal (turmas abertas, já salvas pela consulta diária), nesta ordem: 1) CEP João Pessoa, 2) demais unidades do Senac PB, 3) Senac EAD. **A busca começa sempre pelo CEP-JP, mas o robô não diz isso ao visitante.** Cada turma é falada com unidade, datas, dias, horário, carga horária, valor e vagas, mais a data da consulta e a ressalva de que mudam; "valor?", "tem vaga?" e "outra opção?" funcionam em seguida. Turmas sem vaga ou já encerradas não são oferecidas. Nunca inventa valor ou turma: só falam dados vindos do portal. O catálogo `knowledge/offers.json` cobre o que o portal não lista (cursos técnicos citados em páginas oficiais e EAD).
- **Sem turma aberta:** o robô avisa que não encontrou turma aberta do assunto, oferece a EAD quando houver e orienta a procurar a unidade do Senac mais próxima, informando qual é pela localização do visitante (calculada no backend, em linha reta, nunca pelo Gemini) ou pela cidade que ele citar; sem nenhuma das duas, pede a cidade.
- **Também:** cursos gratuitos (Programa Senac de Gratuidade, sempre com a ressalva de que nem todo curso é gratuito), Senac Empresas para quem fala como empresa, ações sociais, e uma sugestão de curso, discreta e sem repetição, ao fim de respostas sobre assuntos relacionados. Quem demonstra desinteresse não recebe mais sugestões.
- **Atualizar o catálogo de ofertas curadas:** edite `knowledge/offers.json` (cada oferta exige fonte oficial e trecho literal de conferência) e rode `python -m backend.knowledge.verify` e os testes. As turmas do portal não passam por aqui: são atualizadas sozinhas todo dia.

## Identidade visual e logotipo
A interface segue a identidade do Senac Paraíba (azul institucional, branco e laranja): palco azul com o "nascer do sol" em laranja atrás do avatar, avatar branco e azul com olhos digitais, fones laranja que brilham ao ouvir e falar, e conteúdo acolhedor sobre cursos, serviços e projetos.

- **Logotipos oficiais:** os arquivos fornecidos pelo Senac ficam em `frontend/brand/` e são usados sem alteração, com altura fixa e largura automática (sem distorcer) e margem de proteção: "Senac" no cabeçalho, versão branca (silhueta feita só por CSS) sobre o palco azul e "Senac Fecomércio Sesc" no rodapé. A versão vertical está disponível, ainda sem uso. Para trocar uma marca, substitua o arquivo mantendo o nome.
- **Cores:** definidas no início de `frontend/app.css` (`--blue-700`, `--orange`, etc.). Se houver o manual de marca, ajuste os valores ali.
- **Origem das respostas:** a tela do visitante não mostra detalhes técnicos da IA. Para conferir se uma resposta veio do Gemini, local ou contingência, marque "Exibir a origem das respostas" no painel do operador.

## Estrutura e documentação
- `backend/` (FastAPI, IA, controlador do robô, hardware), `frontend/` (HTML/CSS/JS/SVG), `scripts/`, `tests/`, `docs/`.
- [CLAUDE.md](CLAUDE.md): arquitetura e regras do projeto.
- [docs/AUDIO_WINDOWS.md](docs/AUDIO_WINDOWS.md): áudio no Windows 11.
- [docs/RELATORIO_TESTES.md](docs/RELATORIO_TESTES.md): resultados dos testes e pendências.

## Privacidade
Nenhum áudio é gravado ou armazenado pela aplicação, não há reconhecimento facial e as conversas não são guardadas (o contexto fica só na memória e é apagado ao encerrar a sessão). O reconhecimento de fala do Chrome/Edge é feito pelo serviço de voz do navegador, que exige internet. E-mails e números longos são removidos antes de qualquer envio ao Gemini.

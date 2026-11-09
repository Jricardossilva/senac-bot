# Relatório de testes — SENAC BOT Virtual

> Atualização visual (identidade Senac Paraíba): 122 testes automáticos, `browser_smoke` 33/33, `browser_voice_failures` 17/17, `browser_demo` 32/32, capturas conferidas em 1920×1080, 1366×768 e 390×844 (sem rolagem horizontal).

Data: 07/11/2026 · Ambiente: Windows 11, Python 3.14, Microsoft Edge (headless) · Gemini: `gemini-3.5-flash-lite`

## Como reproduzir
```powershell
.\.venv\Scripts\python.exe -m pytest                                  # 113 testes automáticos
powershell -File scripts\run.ps1                                      # em outro terminal, o servidor
.\.venv\Scripts\python.exe tests\e2e\browser_smoke.py http://127.0.0.1:8000/            # 33 verificações no Edge
.\.venv\Scripts\python.exe -u tests\e2e\browser_conversation.py http://127.0.0.1:8000/   # conversa por voz (dublês de voz; ~4 min, um navegador por cenário)
.\.venv\Scripts\python.exe tests\e2e\browser_demo.py http://127.0.0.1:8000/             # 32 verificações no Edge (~1 min)
```
Resultado desta rodada: **113/113** (pytest), **33/33** (interface), **17/17** (falhas de voz) e **32/32** (preparação para o evento e demonstração).

Legenda: **OK** = verificado automaticamente · **OK (manual)** = verificado por mim com o sistema real, sem teste repetível · **PENDENTE** = não foi possível verificar nesta rodada.

## 1. Funcionalidades

| Item | Resultado esperado | Resultado obtido | Situação |
|---|---|---|---|
| Inicialização | App sobe sem chave Gemini; `/health` responde; página inicial servida | `test_app_starts_without_gemini_key`, `test_health_*`, `test_homepage_is_available` passam; Edge carrega a página e conecta | OK |
| Frontend | Quatro ambientes (visitante, operador, simulador, diagnóstico) sem erro de JS, sem rolagem horizontal em 390 px | 33/33 em `browser_smoke.py`, incluindo troca de telas e layout móvel | OK |
| Backend | Rotas de sessão, emergência, ações, sensores, chat e verificação do Gemini | `test_health.py` e `test_robot.py` (49 testes) | OK |
| WebSocket | `/ws/status` envia o estado inicial e cada mudança; página reconecta sozinha | `test_status_websocket_pushes_changes`; Edge mostra "Sistema conectado" via socket | OK |
| Gemini | Chave real responde, origem `gemini` exibida, contexto mantido, sem inventar preços | Verificação `available`; 3 perguntas abertas respondidas (uma recusou inventar valores de curso); modelo anterior (`gemini-3.6-flash`) estourava o timeout e foi trocado | OK (manual) |
| Respostas locais | 16 respostas pedidas, curtas (≤ 70 palavras), sem internet | `test_required_local_answers_exist_and_are_short` (16 casos) | OK |
| Microfone integrado | Dispositivo detectado e permissão consultada | Diagnóstico exibe "1 microfone(s)" e estado da permissão | OK (manual) |
| Reconhecimento de fala | Voz real vira texto em pt-BR e é enviada ao chat | Não testado com voz humana (o navegador headless não tem áudio) | **PENDENTE** |
| Síntese de voz | Voz pt-BR selecionada; parar e repetir; avatar sincronizado | Voz "Microsoft Francisca Online (Natural) – pt-BR" detectada; fluxo de interrupção coberto pelo código e por `browser_voice_failures.py`; reprodução audível não verificada | PENDENTE (audição) |
| Avatar | Expressões e olhos animados | Capturas de tela conferidas (feliz, surpreso, comemorando) | OK (manual) |
| Movimentos | 11 movimentos + aguardar; gestos voltam ao neutro em 3 s; rodas persistem | `test_every_allowed_action_is_accepted` (19 ações), `test_gesture_returns_to_idle_but_wheels_persist`; E2E "wave volta a idle" | OK |
| Sensores simulados | Distância, proximidade, obstáculo, conexão, motores; controles alteram os valores | `test_sensor_snapshot_and_derived_values`; E2E altera o controle deslizante e vê o obstáculo | OK |
| Simulador | 8 expressões e 12 movimentos funcionais; reage à conversa | E2E clica em todos os grupos; `test_chat_reaction_*` | OK |
| Hardware LEGO SPIKE Prime | BLE, handshake, limites, reconexão testados em hardware real | **Não implementado** (Prompt 6 exige inventário real e testes com o Hub) | **PENDENTE** |

## 2. Cenários de falha

| Cenário | Resultado esperado | Resultado obtido | Situação |
|---|---|---|---|
| Sem internet | Gemini cai na contingência local; chat continua | `test_gemini_network_failure_is_unavailable`, `test_api_failures_fall_back_locally[unavailable]`, `test_api_key_never_reaches_the_browser` (cliente sem rede) | OK |
| Gemini sem chave | Status `not_configured`; respostas locais; sem erro fatal | `test_not_configured_uses_fallback_without_calling_provider` | OK |
| Chave inválida | Status `invalid_key`; sem novas chamadas; contingência | `test_invalid_key_stops_further_api_calls`; chamada real com chave falsa devolveu `invalid_key` | OK |
| Cota esgotada (429) | Status `rate_limited`; contingência | `test_gemini_maps_rate_limit_and_missing_model`, `test_api_failures_fall_back_locally[rate_limited]` (429 simulado; cota real não esgotada) | OK (simulado) |
| Modelo descontinuado/inexistente | Status `model_unavailable` | Teste do 404; o `gemini-2.5-flash-lite` devolveu 404 de verdade na API | OK |
| Resposta vazia/bloqueada | Contingência sem marcar a API como fora do ar | `test_empty_response_*` | OK |
| Microfone sem permissão | Mensagem clara; texto segue disponível; captura de teste não inicia | `browser_voice_failures.py` (rejeição `NotAllowedError` reproduzida) | OK |
| Microfone indisponível | Mensagem "Nenhum microfone disponível"; estado Erro volta a Aguardando em 7 s | `browser_voice_failures.py` | OK |
| Navegador sem reconhecimento de voz | Botão de voz desabilitado com aviso; digitar continua | `browser_voice_failures.py` | OK |
| Voz sintetizada indisponível | Resposta continua na tela, aviso exibido, sem erro de JS | `browser_voice_failures.py` | OK |
| Hub desconectado | Movimentos interrompidos, expressão "desconectado", comandos bloqueados exceto parar | `test_disconnection_halts_and_blocks_commands` (**simulador**; Hub físico não existe nesta versão) | OK (simulado) |

## 3. Segurança

| Item | Resultado esperado | Resultado obtido | Situação |
|---|---|---|---|
| Segurança da chave | Chave nunca aparece em rotas, WebSocket nem arquivos estáticos | `test_api_key_never_reaches_the_browser`, `test_frontend_files_do_not_mention_the_key_variable`; `.env` no `.gitignore` | OK |
| Áudio | Nada gravado ou armazenado | `test_no_audio_is_recorded_or_stored`; microfone liberado após o teste de nível (`test_microphone_is_released_after_diagnostic_capture`) | OK |
| Reconhecimento facial | Inexistente | `test_no_facial_recognition` | OK |
| Dados pessoais | E-mail e números longos removidos antes do Gemini | `test_personal_data_is_redacted_before_sending` | OK |
| Limites de movimentação | Avanço bloqueado com obstáculo < 20 cm; rodas param se o obstáculo surge em movimento | `test_obstacle_blocks_forward_but_not_backward`, `test_obstacle_appearing_while_moving_stops_wheels` | OK |
| Parada de emergência | Bloqueia ações e chat; libera e retoma | `test_emergency_stop_blocks_every_command` e E2E | OK |
| Comandos não autorizados | Ações fora da lista recusadas (422); IA sem acesso ao controlador | `test_unlisted_action_is_rejected`, `test_ai_layer_cannot_reach_the_controller` | OK |

## 4. Erros encontrados nesta rodada e corrigidos
1. **Gemini lento e modelo descontinuado:** `gemini-2.5-flash` está descontinuado e o `gemini-3.6-flash` levava 8 a 30 s (acima do timeout, tudo caía na contingência). Padrão trocado para `gemini-3.5-flash-lite` (~2 s).
2. **Quebra total da página sem `speechSynthesis`:** o construtor da síntese acessava `getVoices` num objeto indefinido e derrubava todo o JavaScript. Detectado pelo teste de falhas de voz; a detecção de suporte foi corrigida.
3. **Nome "SENAC BOT" sobreposto às rodas** do robô na tela do visitante (palco e avatar reajustados).
4. **Estado antigo persistia ao iniciar sessão** (por exemplo, expressão "surpreso"): iniciar sessão agora devolve o robô ao neutro.
5. **Palco do simulador distorcido** pela coluna de controles alta: agora fixo no topo (sticky).
6. Saudação com texto extra ("Olá, o que é tecnologia?") e "oi" dentro de outras palavras: tratados na rodada anterior.

## 5. Preparação para o evento (Prompt 8)

| Item | Resultado esperado | Resultado obtido | Situação |
|---|---|---|---|
| Inicialização simplificada | `iniciar.bat`/`run.ps1` instala sozinho, avisa porta ocupada e abre o navegador | `run.ps1 -NoBrowser -Port 8766` subiu e respondeu `/health`; segunda instância na mesma porta recusou com mensagem clara. Instalação do zero verificada numa cópia sem `.venv` nem `.env`: `run.ps1` criou o ambiente, instalou as dependências ("Imports OK"), gerou o `.env`, subiu o servidor e `/health` respondeu `not_configured` | OK (manual) |
| Verificação de internet | Aviso claro e contingência quando offline | `test_preflight_without_internet_warns_and_stays_ready`, `test_check_internet_returns_false_when_unreachable` | OK |
| Verificação do Gemini | Mensagem e ação para: sem chave, chave inválida, cota, modelo, indisponível | `test_preflight_gemini_messages_are_clear` (4 casos) e verificação real "Disponível" | OK |
| Verificação de áudio | Microfone, reconhecimento e voz verificados no navegador | `browser_demo.py` confere os 7 itens da lista; cenários de falha em `browser_voice_failures.py` | OK |
| Verificação do hardware | Modo ativo e falha do físico explicados | `test_build_preflight_reports_hardware_failure`, E2E do modo físico | OK |
| Modo simulado / modo físico | Alternância; físico falha com mensagem clara e simulador segue ativo | `test_physical_mode_fails_clearly_and_simulator_stays_active`, `test_activating_simulator_clears_hardware_error`, `ROBOT_MODE=physical` aceito na configuração. **O modo físico em si não existe** | OK (simulador) / físico PENDENTE |
| Botões iniciar demonstração, encerrar sessão, parada de emergência | Funcionais e coerentes entre si | `test_demo_*` (4 testes) e E2E (iniciar, encerrar no meio, emergência encerra a demonstração, bloqueio e liberação) | OK |
| Roteiro da demonstração | Cumprimenta, apresenta-se, explica, pergunta, responde, propõe desafio, expressões, movimentos, despede-se | E2E percorre o roteiro inteiro: janela de perguntas, resposta local durante a demo, desafio local, expressões (surpreso/triste), movimentos (olhar, inclinar, girar), despedida, robô volta a neutro/idle | OK |
| Sem internet/Gemini na demonstração | Roteiro e perguntas continuam com respostas locais | `test_demo_works_without_gemini_or_internet` | OK |
| Hardware falha na demonstração | Simulador continua utilizável | `test_physical_mode_fails_clearly_and_simulator_stays_active` (ação executada logo após a falha) | OK |
| README | Instalação, configuração, execução, operação e solução de problemas | Reescrito | OK |

## 6. Definição de conclusão (Parte V)

| Critério | Situação |
|---|---|
| Aplicação inicia no Windows 11 | OK |
| Scripts PowerShell funcionais | OK (instalação do zero verificada; `run.ps1` com verificação de porta) |
| Interface visitante, painel do operador, avatar animado | OK |
| Conversação por texto | OK |
| Gemini integrado / respostas locais | OK (testado com chave real) |
| Microfone integrado detectado | OK (1 dispositivo detectado) |
| Reconhecimento de voz | Implementado; **falta teste com voz humana** |
| Síntese de voz | Implementada; voz pt-BR detectada; **falta ouvir no alto-falante** |
| Expressões sincronizadas | OK |
| Simulador, movimentos e sensores simulados | OK |
| Integração LEGO testada, se disponível | **Não disponível / não implementada** |
| Parada de emergência | OK |
| Modo contingência | OK |
| Documentação | OK |
| **Ensaio geral** | **PENDENTE: executar no notebook do evento** (verificação do sistema, teste de voz real, demonstração completa e pergunta falada) |


## 7. Conversa por voz como interação principal

Testada no Edge headless com dublês de voz (`tests/e2e/_browser.py`): `browser_conversation.py` (104 verificações). Os dublês simulam fala, silêncio, erros do reconhecimento, fim da síntese e microfone; **não substituem o teste com voz humana e som real**.

| Item | Resultado esperado | Resultado obtido | Situação |
|---|---|---|---|
| Tela do visitante | Sem campo de texto, formulário, botão enviar nem dados técnicos da IA; botão INICIAR CONVERSA | Verificado no navegador e por `test_visitor_screen_is_voice_first` | OK |
| Iniciar conversa e permissão | Solicita o microfone, abre a sessão, passa a ouvir; microfone aberto só para a permissão e fechado na hora | Estados Solicitando -> Ouvindo; `opened === stopped` | OK |
| Primeira pergunta | Só o texto reconhecido vai ao `/chat`; resposta falada; legendas | OK | OK |
| Reconhecimento pausado durante a fala | O reconhecimento não roda enquanto o robô fala | `__fake.running === false` durante a fala | OK |
| Retomada automática da escuta | Volta a ouvir sozinho, sem novo clique | Cliques totais = 1 em seis perguntas seguidas | OK |
| Várias perguntas consecutivas | Seis perguntas sem novo toque | OK | OK |
| Não reconhecer a própria voz | Frase igual à resposta do robô é descartada | `/chat` não é chamado; segue ouvindo | OK |
| Processamento duplicado | Resultado duplicado ou mesma frase em seguida é processado uma vez | OK | OK |
| Pausas e fim inesperado | Fim sem erro reinicia; silêncio segue ouvindo e orienta; sem resultado vira erro leve e volta a ouvir | OK | OK |
| Falha de conexão | Erro leve com retentativa; após várias falhas, voz indisponível | OK | OK |
| Interrupção da fala | Botão Interromper fala cancela a voz e volta a ouvir | OK | OK |
| Encerrar conversa | Para o reconhecimento, cancela a fala, fecha a sessão, libera o microfone e não volta a ouvir | OK (inclusive durante a fala) | OK |
| Inatividade, emergência, trocar de tela | Encerram a conversa e liberam o microfone | OK | OK |
| Microfone indisponível / permissão negada / ocupado / sem API / sem reconhecimento | Estado "indisponível" com mensagem clara, sem campo de texto, botão para tentar de novo, sessão não aberta | OK (6 cenários) | OK |
| Erros definitivos durante a conversa (`not-allowed`, `audio-capture`) | Indisponível e microfone liberado | OK | OK |
| Sem síntese de voz | Resposta nas legendas e escuta retorna depois do tempo de leitura | OK | OK |
| Operador | Teste de mensagem por texto fora da tela do visitante | OK | OK |
| Voz humana real e som real | Reconhecimento e fala com microfone e alto-falante reais | Não testado automaticamente | **PENDENTE** |

Defeitos encontrados e corrigidos nesta rodada: síntese que lança erro deixava a conversa presa em "falando" (agora segue pela legenda); vigia de reinícios contava reinícios normais (agora só os seguidos sem fala); legendas da demonstração eram apagadas ao abrir a janela de perguntas; o encerramento dos navegadores de teste deixava processos para trás.

## 8. Base de conhecimento institucional (Senac Brasil, Senac PB, CEP-JP)

Testes: `tests/test_knowledge_store.py`, `test_knowledge_search.py`, `test_knowledge_facts.py`, `test_knowledge_updater.py`, `test_chat_knowledge.py`. Consulta real às 20 fontes oficiais em 07/11/2026: **20 fontes consultadas, 0 falhas**, todos os marcadores de validação presentes; 1 fonte dinâmica (programação de cursos) detectada como não verificável automaticamente.

| Item | Resultado esperado | Resultado obtido | Situação |
|---|---|---|---|
| Estrutura e validação | 8 categorias, 3 níveis, toda entrada institucional com fonte oficial (HTTPS, `senac.br`), datas válidas, ids únicos, texto falável (até 90 palavras) | Base real validada sem erros; validações negativas (sem fonte, domínio não oficial, data inválida, id duplicado, unidade inexistente, texto longo, categoria no arquivo errado) recusadas | OK |
| Fatos x páginas oficiais | Cada telefone, endereço, data e nome afirmado aparece no texto da página oficial | Conferência automática contra o texto guardado de cada página (`knowledge/fact_checks.json`, `python -m backend.knowledge.verify`) | 53 de 53 conferências OK (suíte completa: 261 testes passando). Dois dados que a página oficial não traz como texto (WhatsApp dos cursos técnicos, @ do Instagram) foram retirados da base |
| Busca | Perguntas encontram a entrada certa; perguntas fora do assunto não são respondidas pela base | 40 perguntas com entrada esperada; 4 perguntas gerais e 3 institucionais sem dados não geram resposta confiante | OK |
| CEP-JP x outras unidades | Entradas de uma unidade nunca são atribuídas a outra; comparações citam cada unidade separada | Pergunta com o CEP-JP exclui CENDEGE, Gastronomia, Dom Ulrico e Tadros; "diferença entre CEP-JP e CENDEGE" devolve uma frase de cada, rotulada | OK |
| Informação não confirmada | Cursos do CEP-JP, valores, vagas, horários, eventos vigentes: "não tenho confirmação" + canal oficial | Entradas `pending`; o Gemini real recusou preço e curso de gastronomia no CEP-JP | OK |
| Divergência entre páginas oficiais | Não escolher um lado | Escola de Gastronomia e Hotelaria, CEP Cajazeiras, CENDEGE e número de unidades do Senac nacional ficam `review` com as duas versões nas notas | OK |
| Atualidade | Notícias e eventos com validade; informação vencida sai com aviso | Notícias de março a maio de 2026 aparecem como "pode ter mudado"; antes da validade saem sem aviso | OK |
| Natureza das ações | Ação permanente x histórico x vigente | Campo `nature`; nenhuma ação consta como "vigente" (nenhuma fonte confirma) | OK |
| Senac Empresas | Identifica quem fala como empresa e apresenta o Senac Empresas, sem valores | "Sou dono de uma empresa e quero treinar minha equipe" apresenta Senac Empresas; a palavra "empresa" sozinha não força a apresentação | OK |
| Gemini com dados oficiais | Só explica os dados; resposta com número inventado é descartada | `test_gemini_answer_with_invented_numbers_is_discarded`, `..._invented_price_...`; verificado ao vivo com o Gemini real | OK |
| Gemini fora do ar | Resposta direta com o texto da base | Sem chave, erro, cota esgotada ou chave inválida: origem "base de conhecimento" | OK |
| Atualizador | robots.txt, domínios oficiais, espaçamento, validação, preservar a última versão, detectar mudança, falha de rede | 22 testes com servidor simulado | OK |
| Conversa por voz e demonstração | Continuam funcionando | A origem passa a poder ser "Base de conhecimento" (visível só ao operador) | OK |

Exemplos reais de perguntas e respostas: `knowledge/EXEMPLOS.md`.

Limites: a programação de cursos por unidade, valores, vagas e horários **não estão disponíveis como texto** nas páginas oficiais (carregadas por JavaScript ou ausentes); estão em `knowledge/pending.json` (20 pendências). A base reflete as páginas em 07/11/2026 e deve ser atualizada antes do evento.

## 9. Regras institucionais, segurança e orientação para cursos

Testes: `tests/test_policy.py` (82), `test_guidance.py` (47), `test_chat_policy.py` (22) e `tests/e2e/browser_guidance.py` (14 verificações no Edge). Todo o código fica no backend (`backend/policy`, `backend/guidance`); nada depende só do prompt do Gemini.

| Tema | Resultado esperado | Resultado obtido | Situação |
|---|---|---|---|
| Informações financeiras internas | Faturamento, receita, orçamento, despesas, balanço, mesmo pedindo estimativa: resposta fixa de que a informação não é pública | 7 formulações bloqueadas; "quanto custa o curso", "receita de bolo", "custos do curso" não são bloqueadas | OK |
| Salários e dados pessoais | Salário/remuneração de equipe, telefone/e-mail/CPF/endereço de pessoas, lista e notas de alunos: recusa | 9 formulações bloqueadas; telefone e e-mail institucionais continuam públicos | OK |
| Documentos e credenciais | Documentos internos, senha, token, chave de API, `.env`, banco de dados: recusa sem confirmar nem negar | 10 formulações bloqueadas; mesma frase sempre, inclusive com insistência ou "sou o diretor" | OK |
| Manipulação | Pedir prompt/instruções, "ignore as regras", outra identidade, modo desenvolvedor/jailbreak, despejar a base: ignorado | 14 formulações; mensagens bloqueadas não chegam ao Gemini nem ao histórico | OK |
| Saída (todas as origens) | Resposta sem vazar instruções, chave da API, e-mail/telefone/CPF fora da base; sem se dizer humana; sem "vagas abertas"/"acontecendo agora"; gratuidade sempre com ressalva; sem URL falada; máx. ~100 palavras | Cada regra testada em unidade e no serviço de chat com um Gemini simulado que tenta violá-la; textos fixos da própria política não são confundidos com vazamento | OK |
| CEP-JP primeiro | Oferta do CEP-JP vem antes de qualquer outra | Provado com oferta de teste do CEP-JP; hoje nenhuma página oficial confirma ofertas do CEP-JP, então o robô diz que procurou lá primeiro e que não tem a programação confirmada | OK (com pendência de dados) |
| Outras unidades do Senac PB | Sem CEP-JP, recomenda outras unidades, mencionando a unidade; unidade confirmada antes de "unidade não informada" | Dom Ulrico, Gastronomia e Hotelaria, Unidades Móveis, CEP Campina Grande, CENDEGE e técnicos do Senac PB; nunca mistura unidades | OK |
| Senac EAD | Só quando não há oferta nas unidades da Paraíba ou quando o visitante pede | "contabilidade" (só EAD) avisa que olhou a educação a distância; "curso EAD" vai direto | OK |
| Fluxo de recomendação | Assunto, objetivo se amplo, uma oferta, motivo, pergunta de detalhes | "Informática" pergunta o objetivo; "programação", "manutenção" e "ferramentas digitais" levam a ofertas diferentes; "sim" dá detalhes, "outra opção" avança sem repetir, "não" não insiste | OK |
| Dados de curso | Nunca preço, carga horária, data, horário, local, modalidade, vagas ou requisitos | Respostas sem dígitos nem "R$"; pergunta de preço/vaga/horário recebe "não tenho confirmados…" e links oficiais; oferta vencida avisa "pode estar desatualizada"; oferta `pending` não é recomendada | OK |
| Cursos gratuitos | Programa Senac de Gratuidade, nunca "todos gratuitos" | Ressalva "nem todos os cursos são gratuitos…" + critério vindo da base; informação sobre o PSG continua na base | OK |
| Empresas | Apresentar o Senac Empresas, sem propostas nem preços | "Sou gerente/dono…" vai à base (Senac Empresas) e termina com a pergunta sugerida | OK |
| Ações sociais | Ações públicas, permanente x pontual, sem afirmar atendimento em andamento | "Projetos sociais e voluntariado" responde com a ação voluntária ("não informa datas nem locais") e pergunta de continuidade; "acontecendo agora" diz que não há confirmação | OK |
| Sem relação com cursos | Responde primeiro; no máximo uma sugestão pertinente, sem repetir e sem insistir | Sugestão curta ("Aliás… Quer saber mais?") após resposta sobre tecnologia; intervalo mínimo de 3 mensagens; nenhuma para "capital da França" ou depois de "não" | OK |
| Interface | Links oficiais na tela sem sair da conversa; URL nunca falada | Botões abaixo da mensagem (nova aba, `https`, `senac.br`); fala sem endereço; a conversa por voz continua; sem erros no console | OK |
| Conferência de fatos do catálogo | Cada oferta tem trecho literal na página oficial | 23 ofertas conferidas contra os snapshots (76/76 conferências OK junto com a base); isso encontrou um trecho incorreto (Dom Ulrico), já corrigido | OK |

Resultado geral: **412 testes automatizados passando** (`pytest`). Testes de navegador: `browser_smoke` 38/38 e `browser_guidance` 14/14. `browser_conversation` é intermitente: passou 104/104 em uma rodada e em outras falhou em verificações de reinício do reconhecimento depois de falhas sintéticas em sequência rápida (guarda contra laços de reinício); não toca no código desta etapa, e a tela do visitante funciona nos outros testes.

Pendências desta etapa: (1) nenhuma página oficial traz a programação do CEP-JP; assim que ela for conhecida, basta cadastrar as ofertas com `unit: "CEP-JP"` em `knowledge/offers.json`; (2) preço, carga horária, datas, horários, vagas e requisitos continuam sem fonte (só a programação oficial, carregada por JavaScript); (3) a detecção de pedidos sigilosos e de manipulação é por padrões de texto: formulações muito diferentes das testadas podem passar à IA, onde ainda valem o prompt e a política de saída; (4) o catálogo cobre os cursos citados nas páginas oficiais consultadas, não toda a programação.

## 10. Revisão integrada e validação institucional (Prompt 5)

Executada em 07/11/2026. Resultado: **560 testes automatizados passando** (`pytest`) e 5 suítes de navegador (Edge headless) aprovadas na última rodada: `browser_smoke` 38/38, `browser_guidance` 14/14, `browser_public_ui` 45/45, `browser_demo` 38/38 e `browser_conversation` 104/104. Esta última já falhou em rodadas anteriores (ver limitações). Também foi feita uma verificação ao vivo com o Gemini real pelo `/chat` (9 perguntas).

| Área da revisão | O que foi verificado | Resultado |
|---|---|---|
| Identidade visual | Paleta Senac (azul, laranja, branco) definida e usada; logotipos oficiais de `frontend/brand` carregam; avatar único em SVG com animação de escuta e de fala; nenhuma imagem externa; capturas em 1920, 1366, 768 e 390 px conferidas | OK, com uma falha corrigida (rolagem horizontal em 768 px) |
| Responsividade | Sem rolagem horizontal, botão INICIAR CONVERSA visível e alvos de toque de pelo menos 32 px em 4 larguras | OK após correção |
| Conversação por voz | Iniciar/encerrar, reconhecer pt-BR, responder por voz, retomar a escuta, ignorar a própria voz, permissões e erros (`browser_conversation`); nenhum `MediaRecorder`, arquivo de áudio ou chave de áudio no armazenamento; captura do microfone aberta e fechada na hora | OK |
| Interface pública | Varredura do texto visível, títulos e atributos da tela do visitante em vários estados (inicial, conversa, recusas, falha do servidor, perda de conexão): sem Gemini, modelo, chave, log, URL ou exceção; falhas mostram mensagens amigáveis; selo de origem oculto para o visitante | OK |
| Conhecimento institucional | 31 perguntas (Senac Brasil, Senac PB, CEP-JP, demais unidades, cursos, PSG, Senac Empresas, ações sociais, educação ambiental, EAD): entrada esperada entre as 3 primeiras, fonte oficial `https` de `senac.br` e data de consulta em cada entrada recuperada; respostas sem Gemini | 31/31 |
| Dados não confirmados | Preço, vagas, horário, carga horária e início de turma: "não tenho confirmado" sem números | OK após correção |
| Recomendação | 10 interesses simulados (ver tabela abaixo) | OK após correções |
| Segurança | 17 pedidos (dados de alunos e funcionários, financeiro, salários, informação administrativa restrita, credenciais, prompt, confidencial, identidade), sem Gemini e com um Gemini simulado que tenta vazar dados | 17/17 |
| Naturalidade | Contexto da conversa, variação de frases, sem recomendações aleatórias, desinteresse respeitado, diálogo completo | OK após correções |
| Sem Gemini | Todas as baterias rodam sem Gemini; erro, cota ou chave inválida caem na base local | OK |

Recomendação (resposta sem Gemini):

| Visitante | Resposta do robô | Prioridade |
|---|---|---|
| Quero aprender programação | Técnico em Jogos Digitais (cita programação); procurou antes no CEP-JP, sem programação confirmada; unidade a confirmar | PB sem unidade informada |
| Quero trabalhar com informática | Pergunta o objetivo (programação, manutenção ou ferramentas digitais) | CEP-JP consultado primeiro |
| Quero abrir uma empresa | Reconhece que não há oferta confirmada de empreendedorismo e indica a programação oficial | sem oferta (nada inventado) |
| Quero capacitar meus funcionários | Senac Empresas, com pergunta de continuidade | Senac Empresas |
| Tenho interesse em gastronomia | Escola Senac de Gastronomia e Hotelaria | outra unidade do Senac PB |
| Quero fazer um curso de beleza | CEP Campina Grande (empresa pedagógica de beleza) | outra unidade do Senac PB |
| Quero aprender sobre empreendedorismo | Igual a "abrir uma empresa" | sem oferta |
| Procuro um curso gratuito | Programa Senac de Gratuidade, com a ressalva de que nem todo curso é gratuito | PSG |
| Quero estudar a distância | Senac EAD | EAD |
| Tenho interesse em projetos sociais | Ações sociais do Senac Paraíba (base social) | base social |

Falhas encontradas e corrigidas nesta revisão:

1. "Quero abrir uma empresa" e "empreendedorismo" caíam em "não tenho essa informação" ou no texto genérico de robótica: agora o robô reconhece que não há oferta compatível e indica a programação oficial.
2. "Tenho interesse em projetos sociais" caía no texto genérico: perguntas e gatilhos de ações sociais acrescentados.
3. "Sou dono de uma loja" respondia com o Programa de Segurança Alimentar: a busca agora rebaixa entradas de nicho (`demote_unless` em `aliases.json`), que só lideram quando a pergunta cita o assunto delas.
4. A detecção de pedido sigiloso não reconhecia "informação confidencial", "informações administrativas restritas" e "a chave que você usa": padrões corrigidos.
5. "Qual o horário das aulas do CEP?" respondia com o perfil da unidade, sem dizer que o dado não está confirmado: agora recebe a resposta de que valores, vagas, datas e horários não constam.
6. Perguntas de acompanhamento ("E qual o telefone?", "Quem pode fazer?", "Tem curso de gastronomia lá?") ignoravam a conversa: agora herdam a unidade e o assunto da sessão (só em memória; apagados ao encerrar).
7. "Sim", "não" e "entendi" sem pergunta pendente recebiam "não sei responder": agora têm respostas curtas e variadas.
8. A frase "Essa pergunta eu ainda não sei responder" repetia: agora alterna entre variações.
9. Rolagem horizontal entre 681 e 900 px (cabeçalho): o cabeçalho passa a quebrar linha.
10. Botões de link das mensagens com altura menor que 36 px: corrigido.
11. `scripts\atualizar-conhecimento.ps1` aparecia com caractere de controle na documentação (corrigido na etapa anterior).

Informações que ainda precisam de validação do Senac PB (ver também `knowledge/pending.json`):

- Programação, cursos e eixos do CEP João Pessoa (nenhuma página oficial os traz como texto); a orientação de cursos só passa a priorizar o CEP-JP quando houver ofertas dele em `knowledge/offers.json`.
- Preço, carga horária, datas, horários, vagas e requisitos de qualquer curso.
- Endereço da Escola de Gastronomia e Hotelaria (Av. Cabo Branco, 2788, ou Av. Antônio Lira, 300) e os dois endereços de Cajazeiras.
- Situação do CENDEGE (em reforma, funcionando no CEP-JP), da Escola Zona Sul (em construção), de Patos e do Centro Tadros (sem dados).
- Número de unidades e de matrículas do Senac Brasil (páginas oficiais divergem).
- Ofertas do Programa Senac de Gratuidade, ações sociais e eventos vigentes; contatos do Senac Empresas; oferta de empreendedorismo.

## 11. Gerenciador de Eventos (plataforma dinâmica de assistentes para eventos)

Testes: `tests/test_eventkb_research.py` (34), `test_eventkb_manager.py` (17), `test_eventkb_chat.py` (28), `test_eventkb_safety.py` (21) e, no navegador, `tests/e2e/browser_events.py` (26 verificações, com `serve_events_demo.py`). Todos os eventos usados nos testes são **fictícios** (Feira de Gastronomia e Feira de Profissões, marcadas SIMULAÇÃO) servidos por uma "internet de mentira": nenhum teste consulta a rede.

| Tema | O que foi verificado | Resultado |
|---|---|---|
| Cadastro | Só 4 campos obrigatórios (nome, área, descrição, datas); datas inválidas e URLs inválidas recusadas; cadastro parcial inicia a preparação; ids únicos e seguros; evento arquivado não é editado | OK |
| Pesquisa | Segue o site oficial e os links dele (programação, visitação, FAQ); no máximo 20 páginas por pesquisa; respeita robots.txt; recusa localhost, redes privadas, `file://`, nomes que resolvem para rede interna; falha de fonte preserva o que existe; páginas iguais vêm do cache | OK |
| Conteúdo | Blocos literais da fonte, classificados em 13 categorias; JSON-LD de eventos lido; pergunta e resposta de FAQ viram um item; todo item guarda fonte, data, origem da aprovação e histórico; nada é inventado quando não há fonte | OK |
| Confiabilidade | Itens de fonte oficial confirmados automaticamente (regra desligável); página que não cita o evento, fonte candidata e de terceiros ficam pendentes/encontradas; datas que divergem do cadastro ou entre fontes ficam "Divergentes"; instrução escondida numa página é rejeitada | OK |
| Validação humana | Aprovar, editar, rejeitar, adicionar e aprovar em lote (nunca divergentes nem rejeitados); texto editado é validado (limite de palavras, sem instrução nem dado sigiloso) | OK |
| Atualização | Mudança de horário atualiza o item, guarda o histórico e registra o aviso; cancelamento marca o item como desatualizado e cria aviso; informação que sumiu da fonte fica desatualizada; item aprovado/editado nunca é sobrescrito (vira proposta, que o operador aprova para aplicar); item rejeitado não volta; atualização programada respeita intervalo, estado e uma pesquisa por vez; pesquisas manuais espaçadas | OK |
| Ativação | Só informação confirmada chega ao visitante; só um evento ativo; trocar desativa o anterior; desativar e arquivar preservam tudo; evento sem informação confirmada não ativa | OK |
| Isolamento | Com Robótica, Gastronomia e Profissões ativados em sequência, nenhuma resposta nem contexto do Gemini traz dado de outro evento; cada evento tem os próprios arquivos | OK |
| Camada 1 | Com qualquer evento ativo: Senac, CEP-JP, PSG e orientação de cursos (prioridade CEP-JP > outras unidades > EAD) continuam respondendo | OK |
| Camada 3 | Pesquisa externa só para perguntas do evento ativo sem dados, exige fonte https pública, descarta resposta com instrução, passa pela política de saída, tem cache e intervalo mínimo, é registrada no histórico sem guardar a pergunta e pode ser desligada | OK com Gemini simulado; **não verificada ao vivo** (a chave estava com limite de cota esgotado) |
| Personalidade | O contexto do evento muda boas-vindas, perguntas sugeridas, prompt e sugestão de curso (tema do evento); identidade, sigilo e segurança não mudam; contatos só são falados se estiverem em itens confirmados | OK |
| Interface | Cadastro, pesquisa, validação, ativação, troca e desativação feitos pelo painel no Edge; a tela do visitante só recebe nome, tema, boas-vindas e sugestões; o painel não aparece para o visitante; erros com mensagem amigável | 26/26 |

Resultado geral desta etapa: **660 testes automatizados passando**; suítes de navegador `browser_smoke` 38/38, `browser_guidance` 14/14, `browser_public_ui` 45/45, `browser_demo` 38/38, `browser_conversation` 104/104 e `browser_events` 26/26.

Falhas encontradas e corrigidas durante a implementação: dois blocos sob o mesmo título eram confundidos como o mesmo item (uma atividade sobrescrevia a outra); propostas de atualização eram marcadas como desatualizadas na mesma pesquisa; "programação" no texto de apresentação classificava o bloco como agenda; blocos formados só por links entravam como informação; pergunta e resposta de FAQ viam itens separados; o nome do evento (presente em todos os itens) impedia a busca de distinguir "onde" de "quando" (busca agora tira o nome e usa a intenção da pergunta); nome que não resolve no DNS era aceito; textos do visitante falavam "no Feira" (agora "no evento ...") e o rodapé fixava "Robótica 2026" (agora segue o evento ativo).

Pendências: (1) a Robótica 2026 está cadastrada só com os dados do projeto: informe o site oficial para pesquisar a programação real; (2) a pesquisa externa e a descoberta do site oficial usam o Gemini com busca e não foram exercitadas com a API real; (3) a extração é heurística (texto literal por blocos): páginas muito dinâmicas (JavaScript), PDFs e redes sociais com login não são lidos, e o operador precisa revisar o resultado; (4) não há autenticação no painel do operador (como no restante do painel); (5) a checagem de endereços internos resolve o nome antes de baixar, sem proteção contra troca de DNS durante a consulta; (6) uma instalação por evento ativo (múltiplos robôs independentes exigem uma pasta `events/` por instalação).

## 12. Redesign dos cartões e fonte oficial de cursos técnicos

Testes: `tests/test_portal.py` (30, sem rede) e `tests/e2e/browser_knowledge.py` (52 verificações no Edge, com `serve_knowledge_demo.py` trabalhando numa cópia temporária dos dados). A extração real foi executada contra a página oficial em 07/11/2026 (consulta educada: robots.txt, 3 requisições por execução).

| Item | Verificado | Resultado |
|---|---|---|
| Cartão BASE DE CONHECIMENTO | Título em destaque, descrição "Informações oficiais do Senac" em segundo plano, ícone, indicadores com números do servidor, fonte oficial cadastrada, extração e decisões do operador | OK |
| Cartão GERENCIADOR DE EVENTOS | Título/descrição pedidos, ícone de calendário, acento laranja (identidade comum), faixa EVENTO ATIVO com o nome e o período reais | OK |
| Cartão de pendências | Número em destaque (20, o total real), texto explicativo, indicador âmbar "Em acompanhamento", quantidade por situação (17 aguardando confirmação, 3 divergentes, 5 entradas desatualizadas) e, pela fonte oficial, 7 com informação a validar, 4 sem solução e 0 resolvidas; botão "Ver pendências" | OK |
| Estados | Hover (sombra), foco por teclado (anel de 3 px), focus-within, `aria-expanded`, sem animação com "reduzir movimento" | OK |
| Acessibilidade | Contraste WCAG AA (4,5:1) medido em títulos, descrições, texto e indicadores; ícones decorativos ocultos para leitor de tela | OK |
| Responsividade | Sem rolagem horizontal e cartões dentro da tela em 1366, 768 e 390 px | OK |
| Visitante | Nenhum cartão, pendência ou URL interna na tela pública | OK |

Resultado desta etapa: **690 testes automatizados passando** e suítes de navegador aprovadas (`browser_knowledge` 52/52).

Análise das 20 pendências (extração de 07/11/2026: 114 turmas, 31 registros, em 7 unidades): **0 resolvidas** (nada foi aprovado pelo operador), **7 com informação encontrada aguardando validação** (lista de cursos do CEP-JP, áreas/eixos do CEP-JP, Tadros, Patos, endereço de Cajazeiras, endereço da Gastronomia e valores/vagas/datas), **4 relacionadas à fonte que continuam sem solução** (horário de atendimento, reforma do CENDEGE, Escola Zona Sul, passo a passo do PSG) e **9 sem relação** com esta página. Divergências encontradas: telefone do CEP-JP e do CEP Campina Grande no portal difere do registrado na base (2 registros "Divergente"); endereço de Cajazeiras no portal é uma terceira versão; o endereço da Gastronomia coincide com a página de unidades (Av. Cabo Branco, 2788) e não com a de João Pessoa. Importante: as turmas listadas hoje são todas de Formação Inicial e Continuada (101) ou sem modalidade (13); o portal não listava turmas técnicas de nível médio na consulta.

Limitações: a listagem de turmas é uma chamada interna da página (`get-turmas.php`) e pode mudar sem aviso; valores e vagas mudam a toda hora e por isso não são falados; o endpoint público devolve campos de credenciais de pagamento do Senac PB (descartados e nunca gravados): recomenda-se avisar o Senac PB; o cruzamento de endereços usa o texto das entradas já registradas (rua, número e telefone) e não é uma validação humana.

## 13. Limitações conhecidas
- Reconhecimento de fala real e áudio audível exigem teste manual com voz humana e alto-falante no notebook do evento (roteiro na aba **Diagnóstico**).
- O reconhecimento do Chrome/Edge depende de internet; sem rede, a tela do visitante avisa que a conversa por voz está indisponível e a equipe usa o cartão "Testar respostas por texto" do operador (as respostas locais e da base funcionam sem internet).
- A latência do Gemini varia com a demanda do modelo; testar na rede do evento.
- Integração física (Prompt 6): não iniciada, depende do inventário de peças e de testes reais com o Hub; o modo físico apenas falha com mensagem clara.
- A demonstração deve rodar em uma única janela do navegador (o roteiro é executado pela página que o iniciou).
- A tela carrega a fonte Plus Jakarta Sans do Google Fonts (único recurso externo); sem internet o navegador usa uma fonte do sistema e o layout continua legível.
- A suíte `tests/e2e/browser_conversation.py` já falhou de forma intermitente em verificações de reinício do reconhecimento após falhas simuladas em sequência rápida (passou 104/104 na última rodada); a causa não foi isolada.
- A detecção de pedidos sigilosos e de manipulação usa padrões de texto: formulações muito diferentes podem passar à IA, onde ainda valem o prompt e a política de saída.

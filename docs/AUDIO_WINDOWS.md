# Áudio no Windows 11 — microfone integrado e voz sintetizada

O SENAC BOT usa o microfone integrado do notebook e os recursos de voz do navegador (Chrome ou Edge). Nada é gravado ou armazenado pela aplicação: não existe `MediaRecorder`, upload de áudio nem escrita de áudio em disco (há testes automáticos para isso).

## 1. Como acessar
Abra **http://localhost:8000** (ou `http://127.0.0.1:8000`, que o `scripts\run.ps1` exibe). O navegador só libera o microfone em contexto seguro, e `localhost` conta como seguro. Acessar por outro nome ou IP da rede (por exemplo `http://192.168.x.x:8000`) bloqueia o microfone.

## 2. Configurações do Windows
1. **Configurações > Privacidade e segurança > Microfone**.
2. Ative **Acesso ao microfone**.
3. Ative **Permitir que aplicativos acessem o microfone**.
4. Ative **Permitir que aplicativos da área de trabalho acessem o microfone**. Chrome e Edge são aplicativos de área de trabalho; sem essa chave eles não recebem áudio, mesmo com tudo liberado no navegador.
5. **Configurações > Sistema > Som > Entrada**: escolha o microfone integrado e confira o medidor de volume ao falar. Se ele não se mexer, o problema está no Windows ou no driver, não no SENAC BOT.

## 3. Permissão do navegador
- Ao tocar em **INICIAR CONVERSA** pela primeira vez, o navegador pergunta se `localhost` pode usar o microfone: escolha **Permitir**. A permissão é lembrada; depois disso o visitante só fala, sem tocar de novo a cada pergunta, e o microfone é liberado ao tocar em **ENCERRAR CONVERSA** (ou após 2 minutos sem fala).
- Para corrigir uma negação: clique no ícone de cadeado ao lado do endereço > **Permissões do site** > Microfone > **Permitir**. Também é possível abrir `edge://settings/content/microphone` ou `chrome://settings/content/microphone`.
- Feche outros aplicativos que usem o microfone (Teams, Zoom, gravador): em alguns drivers o uso exclusivo impede a captura.

## 4. Tela de diagnóstico
Abra a aba **Diagnóstico** antes de atender visitantes. Ela mostra contexto seguro, permissão, dispositivo detectado, suporte a reconhecimento e voz, estado da captura e texto reconhecido, e oferece:
- **Testar microfone**: captura 5 segundos só para desenhar o nível de áudio e encerra o microfone em seguida. Nada é gravado.
- **Testar reconhecimento**: uma captura de fala com o texto exibido na tela.
- **Testar voz** / **Parar voz**: toca uma frase de exemplo e permite interromper.

## 5. Reconhecimento de fala (decisão técnica)
- **Usado:** Web Speech API do Chrome/Edge, em `pt-BR`, com captura push-to-talk (uma captura por toque, encerrada ao receber a fala, por silêncio ou em 12 s).
- **Atenção:** o reconhecimento do Chrome/Edge envia o áudio ao serviço de voz do navegador e **exige internet**. A aplicação não grava nem guarda esse áudio, mas o fornecedor do navegador o processa. Sem internet, a interface avisa e o visitante usa o campo de texto, e a demonstração continua.
- **Vosk e faster-whisper (offline):** avaliados e **não instalados**. São dependências pesadas (modelos de centenas de MB a GB, e o faster-whisper pede CPU/GPU potente para responder em tempo real), e não há evidência de necessidade: o evento terá internet e o fallback por texto já cobre a falha. Reavaliar apenas se a rede do evento se mostrar instável; nesse caso medir primeiro a CPU e a RAM do notebook com o modelo `small`/`base` antes de adotar.

## 6. Síntese de voz
- Usa a `SpeechSynthesis API` do navegador, com voz `pt-BR` quando existe (prefere vozes "Natural", "Online" ou "Google"), velocidade 0,95 e volume máximo.
- Botão **Interromper fala** na tela do visitante (aparece enquanto o robô fala); a escuta recomeça sozinha. O robô só volta a ouvir depois de terminar de falar, e ignora o que soar como a própria resposta, para não responder a si mesmo. Em notebook, fones ajudam a evitar eco.
- Sem voz em português ou sem síntese, a resposta continua visível e a interface informa o problema.
- Para mais vozes no Windows: **Configurações > Hora e idioma > Fala > Gerenciar vozes**. No Edge, as vozes "Natural" (como Francisca) exigem internet.

## 7. Solução de problemas
| Sintoma | Causa provável | O que fazer |
|---|---|---|
| "Permissão do microfone negada" | Permissão do site ou do Windows | Seções 2 e 3 |
| "Nenhum microfone disponível" | Dispositivo desativado ou driver | Configurações > Sistema > Som > Entrada |
| "O reconhecimento precisa de internet" | Sem rede | Digitar a mensagem |
| "O microfone abriu, mas não captou nenhum som" | Microfone errado, mudo ou volume de entrada zerado | Configurações > Sistema > Som > Entrada: escolha o microfone integrado e fale vendo o medidor |
| "O navegador não conseguiu abrir o microfone" | Outro programa usando o microfone, ou dispositivo errado | Feche Teams/Zoom/gravador e escolha o dispositivo de entrada |
| "Ouvi sua voz, mas o serviço não devolveu o texto" | Sem internet ou reconhecimento online desligado | Ative Configurações > Privacidade e segurança > Fala > **Reconhecimento de voz online**; confira a internet; teste no Chrome |
| Botão de voz desabilitado | Navegador sem Web Speech API (por exemplo Firefox) | Usar Chrome ou Edge |
| Robô não fala | Volume do Windows/aba silenciada, ou sem voz | Aba Diagnóstico > Testar voz |

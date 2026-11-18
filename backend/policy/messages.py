"""Textos fixos da política institucional (nunca gerados pela IA)."""

# Resposta única para qualquer pedido de informação não pública: não confirma nem nega que ela exista.
CONFIDENTIAL = (
    "Essa informação não é pública e não posso compartilhá-la. "
    "Posso ajudar com informações institucionais e serviços que o Senac disponibiliza publicamente."
)

# Tentativas de mudar regras/identidade ou de ver instruções e configurações internas.
MANIPULATION = (
    "Eu sigo sempre as mesmas regras e não posso alterá-las nem detalhá-las. "
    "Sou o assistente virtual do Senac e posso ajudar com informações públicas, cursos e oportunidades. "
    "O que você gostaria de saber?"
)

# Crítica ou opinião negativa sobre o Senac: defende sem concordar, sem atacar e sem afirmar fatos não confirmados.
CRITICISM = (
    "Entendo a sua dúvida. Eu acredito no trabalho do Senac e posso te mostrar, com informações oficiais, "
    "o que ele oferece. Qual assunto ou curso te interessa?"
)

# Crítica com tema reconhecido: reconhece a preocupação (sem concordar) e a converte em ponto forte, só com fatos já
# presentes na base institucional (programa de gratuidade com ressalva, várias unidades, EAD, atuação desde 1946).
CRITICISM_BY_TOPIC: dict[str, str] = {
    "preco": (
        "Entendo a preocupação com o investimento. O Senac tem o Programa Senac de Gratuidade, com cursos gratuitos "
        "para quem atende aos critérios, e o valor de cada turma aparece na programação oficial. "
        "Posso ver uma turma que caiba no seu objetivo. Qual assunto te interessa?"
    ),
    "localizacao": (
        "Entendo a preocupação com a distância. O Senac tem várias unidades e também o Senac EAD, para estudar "
        "de onde você estiver. Posso procurar o que for mais perto ou a distância. Em qual cidade você está?"
    ),
    "demora": (
        "Entendo a preocupação com prazos. O Senac atua desde 1946 e mantém a programação de turmas atualizada "
        "no portal oficial, com datas e horários de cada uma. Posso te mostrar uma turma com início próximo. "
        "Qual assunto te interessa?"
    ),
    "estrutura": (
        "Entendo a preocupação com a estrutura. O Senac tem tradição de formação profissional desde 1946, "
        "com cursos voltados ao mercado de trabalho. Posso te mostrar o que cada curso oferece. "
        "Qual área te interessa?"
    ),
    "qualidade": (
        "Entendo a dúvida sobre a qualidade. Eu acredito no trabalho do Senac, que forma profissionais desde 1946 "
        "com cursos voltados ao mercado de trabalho. Posso te mostrar, com informações oficiais, o conteúdo "
        "de um curso. Qual assunto te interessa?"
    ),
}

# Pergunta neutra sobre defeitos/pontos fracos do Senac: não inventa defeito nem concorda; volta aos pontos fortes.
WEAK_POINTS = (
    "Não tenho uma lista de defeitos para apontar. O que posso fazer é te mostrar os pontos fortes do Senac: "
    "tradição desde 1946, várias unidades, cursos presenciais e a distância e o Programa Senac de Gratuidade, "
    "que depende dos critérios de cada oferta. Qual assunto te interessa?"
)

# Pedido de avaliar/comparar outras instituições, empresas ou projetos: o robô não opina.
NO_EVALUATION = (
    "Eu sou o assistente virtual do Senac e não avalio nem comparo outras instituições, empresas ou projetos. "
    "Posso te contar com prazer o que o Senac oferece. Qual área te interessa?"
)

IDENTITY ="Sou o assistente virtual do Senac, um robô. Não sou uma pessoa nem um funcionário."

# Gratuidade nunca é geral: depende da oferta.
FREE_CAVEAT = (
    "Nem todos os cursos são gratuitos: a gratuidade depende da programação, dos critérios e das condições de cada oferta."
)

UNCONFIRMED_AVAILABILITY = (
    "Não tenho confirmação de vagas, turmas ou inscrições abertas. "
    "Para saber a situação atual, consulte a programação oficial do Senac Paraíba."
)

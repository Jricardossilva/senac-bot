"""Lista de comandos permitidos do robô (única fonte de verdade) e regras de segurança numéricas."""

EXPRESSIONS: dict[str, str] = {
    "neutral": "Neutro",
    "happy": "Feliz",
    "curious": "Curioso",
    "thinking": "Pensando",
    "speaking": "Falando",
    "surprised": "Surpreso",
    "sad": "Triste",
    "disconnected": "Desconectado",
}

MOVEMENTS: dict[str, str] = {
    "idle": "Aguardando",
    "look_left": "Olhando para a esquerda",
    "look_right": "Olhando para a direita",
    "tilt_head": "Inclinando a cabeça",
    "left_arm": "Movendo o braço esquerdo",
    "right_arm": "Movendo o braço direito",
    "wave": "Cumprimentando",
    "celebrate": "Comemorando",
    "wheels_forward": "Rodas para frente",
    "wheels_backward": "Rodas para trás",
    "spin": "Girando",
    "stop": "Parado",
}

ALLOWED_ACTIONS: frozenset[str] = frozenset(EXPRESSIONS) | frozenset(MOVEMENTS)

# Movimentos que voltam sozinhos à posição neutra; os demais (rodas, parar) persistem até novo comando.
MOMENTARY_MOVEMENTS: frozenset[str] = frozenset(
    {"look_left", "look_right", "tilt_head", "left_arm", "right_arm", "wave", "celebrate", "spin"}
)
GESTURE_SECONDS = 3.0

# Sensor frontal simulado
OBSTACLE_CM = 20  # abaixo disso: obstáculo; avanço bloqueado
NEAR_CM = 50  # abaixo disso: objeto próximo

# Reação do robô à conversa: intenção -> (expressão, movimento opcional). Decidida pelo backend.
REACTIONS: dict[str, tuple[str, str | None]] = {
    "greeting": ("happy", "wave"),
    "farewell": ("happy", "wave"),
    "thanks": ("happy", None),
    "joke": ("happy", None),
    "challenge": ("curious", None),
    "question": ("curious", None),
    "info": ("happy", None),
}
DEFAULT_REACTION: tuple[str, str | None] = ("curious", None)

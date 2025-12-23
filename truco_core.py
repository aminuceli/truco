import random

# Valores das cartas para manilha (Zap, Copas, Espadilha, Ouros)
NAIPES = {
    'Ouros': 1,
    'Espadas': 2,
    'Copas': 3,
    'Paus': 4
}

# Ordem de força (do menor para o maior, sem manilha)
FORCA_PADRAO = ['4', '5', '6', '7', 'Q', 'J', 'K', 'A', '2', '3']

class Carta:
    def __init__(self, valor, naipe):
        self.valor = valor
        self.naipe = naipe

    def __repr__(self):
        return f"{self.valor} de {self.naipe}"

class TrucoGame:
    def __init__(self):
        self.baralho = []
        self.vira = None
        self.manilha_da_rodada = None
        self.resetar_baralho()

    def resetar_baralho(self):
        """Cria um baralho limpo e embaralhado"""
        valores = ['4', '5', '6', '7', 'Q', 'J', 'K', 'A', '2', '3']
        naipes_lista = list(NAIPES.keys())
        self.baralho = [Carta(v, n) for v in valores for n in naipes_lista]
        random.shuffle(self.baralho)

    def dar_cartas(self, num_jogadores):
        """Distribui 3 cartas para cada jogador e define o Vira"""
        cartas_necessarias = (num_jogadores * 3) + 1
        if len(self.baralho) < cartas_necessarias:
            self.resetar_baralho()
        
        maos = []
        for _ in range(num_jogadores):
            mao_jogador = [self.baralho.pop() for _ in range(3)]
            maos.append(mao_jogador)
            
        self.vira = self.baralho.pop()
        self.definir_manilha()
        
        return maos, self.vira

    def definir_manilha(self):
        """Define qual é a carta forte com base no Vira"""
        idx_vira = FORCA_PADRAO.index(self.vira.valor)
        idx_manilha = (idx_vira + 1) % len(FORCA_PADRAO)
        self.manilha_da_rodada = FORCA_PADRAO[idx_manilha]

    def calcular_forca(self, carta):
        if carta.valor == self.manilha_da_rodada:
            return 100 + NAIPES[carta.naipe]
        return FORCA_PADRAO.index(carta.valor)

class Mao:
    def __init__(self, jogo):
        self.jogo = jogo
        self.rodadas = [] # 0, 1 ou -1 (empate)
        self.vencedor_mao = None 
        
        # Estado da Aposta
        self.valor_atual = 1 
        self.dono_atual_da_aposta = None 

    def get_proximo_valor(self):
        sequencia = {1: 3, 3: 6, 6: 9, 9: 12}
        return sequencia.get(self.valor_atual, None)

    def pode_pedir_aumento(self, jogador_id):
        # TRAVA DE SEGURANÇA
        if self.valor_atual >= 12:
            return False, "A aposta já está no máximo (12)!"
        
        # Se eu já sou o dono, não posso pedir em cima do meu pedido
        if self.dono_atual_da_aposta == jogador_id:
            proximo = self.get_proximo_valor()
            return False, f"Você já tem o controle. Aguarde o adversário pedir {proximo}."
            
        return True, "Pode pedir"

    def verificar_fim_mao(self):
        """
        Regra: Quem ganha 2 rodadas leva.
        Empate na 1ª -> Quem ganha a 2ª leva.
        Empate na 1ª e 2ª -> Quem ganha a 3ª leva.
        Empate na 1ª, 2ª e 3ª -> Ninguém ganha.
        Vencedor na 1ª e Empate na 2ª -> Quem ganhou a 1ª leva.
        """
        r = self.rodadas
        
        if len(r) < 2: return

        # 1. Vitória Limpa (2x0 ou 2x1)
        if r.count(0) == 2:
            self.vencedor_mao = "Time 0"
            return
        if r.count(1) == 2:
            self.vencedor_mao = "Time 1"
            return

        # 2. Primeira Empatada (Canga)
        if r[0] == -1:
            if r[1] == 0: self.vencedor_mao = "Time 0"
            elif r[1] == 1: self.vencedor_mao = "Time 1"
            elif len(r) == 3:
                if r[2] == 0: self.vencedor_mao = "Time 0"
                elif r[2] == 1: self.vencedor_mao = "Time 1"
                else: self.vencedor_mao = "Ninguém"

        # 3. Primeira com Vencedor, Segunda Empatada -> FIM DE JOGO
        elif r[1] == -1:
            if r[0] == 0: self.vencedor_mao = "Time 0"
            elif r[0] == 1: self.vencedor_mao = "Time 1"
        
        # 4. Terceira Empatada
        elif len(r) == 3 and r[2] == -1:
             if r[0] == 0: self.vencedor_mao = "Time 0"
             elif r[0] == 1: self.vencedor_mao = "Time 1"
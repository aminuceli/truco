import random

# ==============================================================================
# CONFIGURAÇÕES DE FORÇA E NAIPES
# ==============================================================================

# Valores dos naipes para Manilhas (Do mais fraco para o mais forte)
# Ouros = 1, Espadas = 2, Copas = 3, Paus (Zap) = 4
NAIPES = {
    'Ouros': 1,
    'Espadas': 2,
    'Copas': 3,
    'Paus': 4
}

# Ordem de força das cartas comuns (do menor para o maior)
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
        """Recria o baralho e embaralha"""
        # Cria todas as combinações de cartas
        valores = ['4', '5', '6', '7', 'Q', 'J', 'K', 'A', '2', '3']
        naipes_lista = list(NAIPES.keys())
        self.baralho = [Carta(v, n) for v in valores for n in naipes_lista]
        random.shuffle(self.baralho)

    def dar_cartas(self, num_jogadores):
        """
        Distribui 3 cartas para cada jogador.
        Retorna: (lista de maos, carta_vira)
        """
        # Verifica se tem carta suficiente, se não, reembaralha
        cartas_necessarias = (num_jogadores * 3) + 1
        if len(self.baralho) < cartas_necessarias:
            self.resetar_baralho()
        
        maos = []
        for _ in range(num_jogadores):
            mao_jogador = []
            for _ in range(3):
                mao_jogador.append(self.baralho.pop())
            maos.append(mao_jogador)
            
        self.vira = self.baralho.pop()
        self.definir_manilha()
        
        return maos, self.vira

    def definir_manilha(self):
        """Define qual carta é a Manilha baseado no Vira"""
        if not self.vira: return
        
        idx_vira = FORCA_PADRAO.index(self.vira.valor)
        # A manilha é a próxima carta na sequência circular
        idx_manilha = (idx_vira + 1) % len(FORCA_PADRAO)
        self.manilha_da_rodada = FORCA_PADRAO[idx_manilha]

    def calcular_forca(self, carta):
        """
        Calcula a força numérica da carta para comparação.
        Quanto maior o número, mais forte a carta.
        """
        # 1. Verifica se é Manilha (Força Máxima)
        if carta.valor == self.manilha_da_rodada:
            # Base 100 + valor do naipe (garante que Zap ganhe de Copas, etc.)
            return 100 + NAIPES[carta.naipe]
            
        # 2. Cartas Comuns (Força baseada na posição do array)
        return FORCA_PADRAO.index(carta.valor)

class Mao:
    def __init__(self, jogo):
        self.jogo = jogo
        self.rodadas = [] # Armazena quem ganhou cada rodada: 0, 1 ou -1 (empate)
        self.vencedor_mao = None 
        
        # Controle de Aposta (Truco, Seis, Nove, Doze)
        self.valor_atual = 1 
        self.dono_atual_da_aposta = None 

    def pode_pedir_aumento(self, jogador_id):
        """Verifica se um jogador pode pedir aumento da aposta"""
        
        # Se já vale 12, não dá pra aumentar mais
        if self.valor_atual >= 12:
            return False, "Valor máximo atingido!"
        
        # Se eu já pedi o truco atual, não posso pedir em cima de mim mesmo
        # (Tem que esperar o adversário aumentar)
        if self.dono_atual_da_aposta == jogador_id:
            return False, "Você já tem o controle da aposta."
            
        return True, "Pode pedir"

    def verificar_fim_mao(self):
        """
        Analisa o histórico de rodadas para definir se alguém ganhou a Mão.
        Regras de Truco Paulista.
        """
        r = self.rodadas
        
        # Precisa de pelo menos 2 rodadas para decidir (exceto 2x0 direto)
        if len(r) < 2: 
            return

        # ==========================================================
        # 1. VITÓRIA DIRETA (Alguém ganhou 2 rodadas)
        # ==========================================================
        if r.count(0) == 2:
            self.vencedor_mao = "Time 0"
            return
        if r.count(1) == 2:
            self.vencedor_mao = "Time 1"
            return

        # ==========================================================
        # 2. REGRAS DE EMPATE (CANGA)
        # ==========================================================
        
        # CASO A: Primeira rodada empatou
        if r[0] == -1:
            # Quem ganhar a segunda, leva a mão
            if r[1] == 0: 
                self.vencedor_mao = "Time 0"
            elif r[1] == 1: 
                self.vencedor_mao = "Time 1"
            elif len(r) == 3:
                # Se empatou a primeira e a segunda, quem ganhar a terceira leva
                if r[2] == 0: self.vencedor_mao = "Time 0"
                elif r[2] == 1: self.vencedor_mao = "Time 1"
                else: self.vencedor_mao = "Ninguem" # Empate nas 3 (raríssimo)

        # CASO B: Primeira teve vencedor, mas a segunda empatou
        elif r[1] == -1:
            # Regra: Empatou a segunda, ganha quem venceu a primeira
            if r[0] == 0: self.vencedor_mao = "Time 0"
            elif r[0] == 1: self.vencedor_mao = "Time 1"
        
        # CASO C: Terceira rodada empatou
        elif len(r) == 3 and r[2] == -1:
             # Regra: Empatou a terceira, ganha quem venceu a primeira
             if r[0] == 0: self.vencedor_mao = "Time 0"
             elif r[0] == 1: self.vencedor_mao = "Time 1"

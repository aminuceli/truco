import random

# Valores dos Naipes para desempate de Manilha
# Pesos: Paus (Zap) > Copas > Espadas > Ouros
NAIPES = {
    'Ouros': 1,
    'Espadas': 2,
    'Copas': 3,
    'Paus': 4
}

# Ordem de força padrão (do menor para o maior, sem manilha)
FORCA_PADRAO = ['4', '5', '6', '7', 'Q', 'J', 'K', 'A', '2', '3']

class Carta:
    def __init__(self, valor, naipe):
        self.valor = valor
        self.naipe = naipe

    def __repr__(self):
        return f"{self.valor} de {self.naipe}"

    # IMPORTANTE: Este método ensina o Python a comparar duas cartas
    # Sem isso, o 'mao.remove(carta)' do server.py falharia
    def __eq__(self, other):
        return isinstance(other, Carta) and self.valor == other.valor and self.naipe == other.naipe

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
        # Garante que tem cartas suficientes
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
        # Se a carta for a Manilha, ela ganha força extra (100 + peso do naipe)
        if carta.valor == self.manilha_da_rodada:
            return 100 + NAIPES[carta.naipe]
        return FORCA_PADRAO.index(carta.valor)

class Mao:
    def __init__(self, jogo):
        self.jogo = jogo
        self.rodadas = [] # 0, 1 ou -1 (empate/canga)
        self.vencedor_mao = None 
        
        # Estado da Aposta
        self.valor_atual = 1 
        self.dono_atual_da_aposta = None 

    def get_proximo_valor(self):
        sequencia = {1: 3, 3: 6, 6: 9, 9: 12}
        return sequencia.get(self.valor_atual, None)

    def pode_pedir_aumento(self, jogador_id):
        # Trava de segurança
        if self.valor_atual >= 12:
            return False, "A aposta já está no máximo (12)!"
        
        # Verificação de Time: Se eu já pedi, não posso pedir de novo em cima
        # (Lógica simplificada para evitar loop de aumento infinito pelo mesmo jogador)
        if self.dono_atual_da_aposta is not None:
            if self.dono_atual_da_aposta == jogador_id:
                return False, "Seu time já tem o controle da aposta."
            
        return True, "Pode pedir"

    def verificar_fim_mao(self):
        """
        Regra: Melhor de 3.
        """
        r = self.rodadas
        
        if len(r) == 0: return

        # 1. Vitória Limpa (2x0)
        if r.count(0) == 2:
            self.vencedor_mao = "Time 0"
            return
        if r.count(1) == 2:
            self.vencedor_mao = "Time 1"
            return

        # Verifica empates
        if len(r) == 2:
            # Empate na 1ª rodada
            if r[0] == -1:
                if r[1] != -1: self.vencedor_mao = f"Time {r[1]}" # Quem ganha a 2ª leva
                return 
            
            # Empate na 2ª rodada
            if r[1] == -1:
                if r[0] != -1: self.vencedor_mao = f"Time {r[0]}" # Quem ganhou a 1ª leva
                return
        
        if len(r) == 3:
            # Caso normal 1-1-1
            if r[2] != -1: 
                self.vencedor_mao = f"Time {r[2]}"
                return
            
            # Empate na 3ª rodada
            if r[2] == -1:
                # Se a 1ª não foi empate, quem ganhou a 1ª leva
                if r[0] != -1: self.vencedor_mao = f"Time {r[0]}"
                elif r[1] != -1: self.vencedor_mao = f"Time {r[1]}"
                else: self.vencedor_mao = "Ninguém" # Raro: 3 empates

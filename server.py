import socketio
import asyncio
import random
import time
import uvicorn
import os
import traceback
from truco_core import TrucoGame, Mao, Carta

# ==============================================================================
# CONFIGURAÇÕES INICIAIS
# ==============================================================================
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

# Arquivos estáticos
static_files = {
    '/': 'index.html',
    '/win.mp3': 'win.mp3',
    '/lose.mp3': 'lose.mp3',
    '/shuffle.mp3': 'shuffle.mp3',
    '/card.mp3': 'card.mp3',
    '/truco.mp3': 'truco.mp3',
    '/truco1.mp3': 'truco1.mp3',
    '/seis.mp3': 'seis.mp3',
    '/nove.mp3': 'nove.mp3',
    '/doze.mp3': 'doze.mp3',
    '/correr.mp3': 'correr.mp3',
    '/correr1.mp3': 'correr1.mp3',
    '/seis1.mp3': 'seis1.mp3',
    '/nove1.mp3': 'nove1.mp3',
    '/doze1.mp3': 'doze1.mp3',

}

app = socketio.ASGIApp(sio, static_files=static_files)

# Listas de sons (SEM .mp3)
SONS_TRUCO = ['truco', 'truco1']
SONS_SEIS  = ['seis', 'seis1']
SONS_NOVE  = ['nove', 'nove1']
SONS_DOZE  = ['doze', 'doze1']
SONS_CORRER = ['correr', 'correr1']

def get_som_aleatorio(lista):
    if not lista:
        return None
    return random.choice(lista)


jogos = {}
ultimos_sinais = {} 
TEMPO_LIMITE_AFK = 60 

# ==============================================================================
# 1. MONITORAMENTO E UTILITÁRIOS
# ==============================================================================

async def loop_monitoramento_afk():
    print("[SISTEMA] Monitor de inatividade iniciado.")
    while True:
        await asyncio.sleep(5)
        agora = time.time()
        sids = list(ultimos_sinais.keys())
        for sid in sids:
            ultimo = ultimos_sinais.get(sid, agora)
            if agora - ultimo > TEMPO_LIMITE_AFK:
                if sid in ultimos_sinais: del ultimos_sinais[sid]
                await gerenciar_desistencia(sid)
                try: await sio.disconnect(sid)
                except: pass

async def emitir_som(nome_sala, som):
    if not som: return
    if nome_sala in jogos:
        sala = jogos[nome_sala]
        for p in sala['jogadores']:
            if not p.startswith('BOT'):
                await sio.emit('tocar_som', {'som': som}, to=p)

async def enviar_estado_mesa(nome_sala):
    if nome_sala not in jogos: return
    sala = jogos[nome_sala]
    lista = []
    for item in sala['mesa_cartas']:
        sid_dono, carta = item
        idx = -1
        if sid_dono in sala['jogadores']:
            idx = sala['jogadores'].index(sid_dono)
        lista.append({'valor': carta.valor, 'naipe': carta.naipe, 'dono_idx': idx})
    
    for p in sala['jogadores']:
        if not p.startswith('BOT'):
            await sio.emit('atualizar_mesa', {'cartas': lista}, to=p)

async def notificar_info_jogo(nome_sala):
    if nome_sala not in jogos: return
    sala = jogos[nome_sala]
    sets_atuais = sala.get('sets', [0, 0])
    try: dono_real_idx = getattr(sala['mao'], 'dono_atual_da_aposta', None)
    except: dono_real_idx = None

    for i, p in enumerate(sala['jogadores']):
        if p.startswith('BOT'): continue
        meu_time = i % 2
        placar_vis = sala['placar'] if meu_time == 0 else sala['placar'][::-1]
        sets_vis = sets_atuais if meu_time == 0 else sets_atuais[::-1]
        dono_para_enviar = dono_real_idx
        if dono_real_idx is not None:
            try:
                dono_idx_int = int(dono_real_idx)
                if (dono_idx_int % 2) == meu_time: dono_para_enviar = i 
            except ValueError: pass 

        await sio.emit('info_jogo', {
            'placar': placar_vis, 'sets': sets_vis,
            'valor': sala['mao'].valor_atual, 'dono_aposta': dono_para_enviar,
            'nomes': sala['jogadores_nomes'], 'seu_indice': i,
            'rodadas_hist': sala['mao'].rodadas
        }, to=p)

async def atualizar_turnos(nome_sala):
    if nome_sala not in jogos: return
    sala = jogos[nome_sala]
    
    if sala['estado_jogo'] in ['MAO_DE_11', 'TRUCO', 'FIM']: return

    vez_idx = sala['vez_atual_idx']
    
    if vez_idx is not None:
        sid_vez = sala['jogadores'][vez_idx]
        for p_sid in sala['jogadores']:
            if not p_sid.startswith('BOT'):
                await sio.emit('status_vez', {'e_sua_vez': (p_sid == sid_vez)}, to=p_sid)
        
        if sid_vez.startswith('BOT'):
            try:
                asyncio.create_task(bot_jogar_delay(nome_sala, vez_idx))
            except Exception as e:
                print(f"ERRO AO INICIAR BOT: {e}")
    else:
        for p_sid in sala['jogadores']:
            if not p_sid.startswith('BOT'):
                await sio.emit('status_vez', {'e_sua_vez': False}, to=p_sid)

# ==============================================================================
# 2. LÓGICA DO JOGO
# ==============================================================================
# ======================================================================
# IA DO BOT — PEDIR TRUCO / SEIS / NOVE / DOZE
# ======================================================================

def bot_deve_pedir_truco(sala, idx_bot):
    mao = sala['maos_server'][idx_bot]
    if not mao:
        return False

    # calcula força das cartas
    forcas = sorted(
        [sala['jogo'].calcular_forca(c) for c in mao],
        reverse=True
    )

    # critérios simples e eficientes
    tem_carta_muito_forte = forcas[0] >= 10
    tem_duas_boas = len(forcas) >= 2 and forcas[1] >= 7

    chance = random.random()  # evita robô perfeito

    if tem_carta_muito_forte and chance < 0.75:
        return True
    if tem_duas_boas and chance < 0.55:
        return True

    return False

async def bot_pedir_truco(nome_sala, idx_bot):
    # BOT inicia o pedido de aumento igual ao humano (evento pedir_truco)
    if nome_sala not in jogos:
        return
    sala = jogos[nome_sala]

    # só pode pedir se estiver jogando e for a vez dele
    if sala['estado_jogo'] != 'JOGANDO':
        return
    if sala['vez_atual_idx'] != idx_bot:
        return

    # respeita regra do core (se existir)
    try:
        pode, msg = sala['mao'].pode_pedir_aumento(idx_bot)
        if not pode:
            return
    except:
        pass

    atual = sala['mao'].valor_atual

    # próximo valor
    if atual == 1:
        novo_valor = 3
    elif atual == 3:
        novo_valor = 6
    elif atual == 6:
        novo_valor = 9
    elif atual == 9:
        novo_valor = 12
    else:
        return

    # muda estado para TRUCO e registra o “pedinte”
    sala['estado_jogo'] = 'TRUCO'
    sala['pedinte_temp'] = idx_bot
    sala['valor_proposto_temp'] = novo_valor

    # toca som certo (truco/seis/nove/doze)
    som_escolhido = get_som_aleatorio(SONS_TRUCO)
    if novo_valor == 6:
        som_escolhido = get_som_aleatorio(SONS_SEIS)
    elif novo_valor == 9:
        som_escolhido = get_som_aleatorio(SONS_NOVE)
    elif novo_valor == 12:
        som_escolhido = get_som_aleatorio(SONS_DOZE)

    await emitir_som(nome_sala, som_escolhido)

    # envia pedido ao próximo jogador (mesma lógica do seu pedir_truco)
    prox = (idx_bot + 1) % sala['max_jogadores']
    sid_op = sala['jogadores'][prox]
    nome_bot = sala['jogadores_nomes'][idx_bot]

    if sid_op.startswith('BOT'):
        asyncio.create_task(bot_responder_truco(nome_sala, prox, novo_valor))
    else:
        await sio.emit('receber_pedido_truco', {'valor': novo_valor, 'quem_pediu': nome_bot}, to=sid_op)
        await sio.emit('aguardando_truco', {}, to=sala['jogadores'][idx_bot])


# ======================================================================
# IA DO BOT — BLEFE (pode pedir aumento mesmo com mão fraca)
# ======================================================================

def bot_deve_blefar(sala, idx_bot):
    mao = sala['maos_server'][idx_bot]
    if not mao:
        return False

    # força das cartas
    forcas = sorted(
        [sala['jogo'].calcular_forca(c) for c in mao],
        reverse=True
    )

    atual = sala['mao'].valor_atual

    # NÃO blefa se já estiver muito alto
    if atual >= 9:
        return False

    chance = random.random()

    # blefe puro (mão fraca, mas arrisca)
    if forcas[0] < 6 and chance < 0.18:
        return True

    # semi-blefe (1 carta média)
    if forcas[0] >= 6 and forcas[0] < 8 and chance < 0.35:
        return True

    return False

async def bot_jogar_delay(nome_sala, idx_bot):
    await asyncio.sleep(1.5)
    try:
        if nome_sala not in jogos: return
        sala = jogos[nome_sala]

        if sala.get('estado_jogo') != 'JOGANDO':
            return
        
        if sala['vez_atual_idx'] != idx_bot: 
            return 
            
        mao_bot = sala['maos_server'][idx_bot]
        if not mao_bot:
            return

        # decide truco / aumento (força real ou blefe)
        if bot_deve_pedir_truco(sala, idx_bot) or bot_deve_blefar(sala, idx_bot):
            await bot_pedir_truco(nome_sala, idx_bot)
            return

        # joga carta normalmente
        carta_escolhida = max(
            mao_bot,
            key=lambda c: sala['jogo'].calcular_forca(c)
        )
        mao_bot.remove(carta_escolhida)

        sid_bot = sala['jogadores'][idx_bot]
        await processar_jogada_carta(
            nome_sala,
            sid_bot,
            carta_escolhida
        )

        
    except Exception as e:
        print(f"ERRO CRÍTICO NO BOT: {e}")
        traceback.print_exc()

async def processar_jogada_carta(nome_sala, sid, carta_obj):
    if nome_sala not in jogos: return
    sala = jogos[nome_sala]
    
    sala['mesa_cartas'].append( (sid, carta_obj) )
    await emitir_som(nome_sala, 'card')
    await enviar_estado_mesa(nome_sala)

    num_p = sala['max_jogadores']
    
    # --- Verifica se a rodada (mesa) está cheia ---
    if len(sala['mesa_cartas']) < num_p:
        sala['vez_atual_idx'] = (sala['vez_atual_idx'] + 1) % num_p
        await atualizar_turnos(nome_sala)
    else:
        # FIM DA RODADA - Todos jogaram
        sala['vez_atual_idx'] = None
        await atualizar_turnos(nome_sala) 
        await asyncio.sleep(1.5)
        
        # --- 1. CALCULA QUEM GANHOU A RODADA (OU EMPATE) ---
        maior_forca = -1
        times_com_maior_forca = set() # Armazena quais times (0 ou 1) têm a maior carta
        
        for item in sala['mesa_cartas']:
            sid_j, c = item
            f = sala['jogo'].calcular_forca(c)
            
            # Descobre o time deste jogador
            idx_jogador = sala['jogadores'].index(sid_j)
            time_jogador = idx_jogador % 2
            
            if f > maior_forca:
                maior_forca = f
                times_com_maior_forca = {time_jogador} # Novo líder
            elif f == maior_forca:
                times_com_maior_forca.add(time_jogador) # Empate potencial
        
        # Decide o resultado da RODADA
        vencedor_rodada = -1 # -1 significa EMPATE (Canga)
        vencedor_txt = "EMPATE (Canga)"
        
        if len(times_com_maior_forca) == 1:
            # Apenas um time tem a carta mais forte
            vencedor_rodada = list(times_com_maior_forca)[0]
            vencedor_txt = "Time A" if vencedor_rodada == 0 else "Time B"
        
        # Adiciona o resultado ao histórico
        sala['mao'].rodadas.append(vencedor_rodada)
        
        # Define quem começa a próxima (quem ganhou ou quem começou a anterior se empatou)
        proximo_a_jogar = -1
        if vencedor_rodada != -1:
            # Procura o jogador desse time que jogou a maior carta para ser o primeiro
            # (Simplificação: pega o primeiro índice desse time que venceu a rodada atual)
            # Para ser exato, deveríamos guardar quem jogou a carta, mas a regra básica manda o vencedor tornar.
            # Vamos achar quem jogou a carta vencedora:
            for item in sala['mesa_cartas']:
                sid_j, c = item
                if sala['jogo'].calcular_forca(c) == maior_forca:
                    idx = sala['jogadores'].index(sid_j)
                    if (idx % 2) == vencedor_rodada:
                        proximo_a_jogar = idx
                        break
        else:
             # Se empatou, quem torna é quem começou a rodada atual (regra comum) ou o "pé"
             # Mas o mais comum no empate é quem "melou" a carta, ou segue a roda. 
             # Vamos manter: quem tornou a rodada atual, torna a próxima.
             # Para isso precisamos saber quem começou essa rodada. Vamos usar lógica de incremento:
             # Se empatou, o próximo é o próximo do 'jogador_inicial_mao' + n_rodada?
             # Simplificação robusta: O mão (primeiro da rodada 1) torna no empate.
             proximo_a_jogar = sala['jogador_inicial_mao']


        # --- 2. LÓGICA DE QUEM LEVA A MÃO (AQUI ESTAVA O ERRO) ---
        r = sala['mao'].rodadas
        venc_mao_int = None 
        
        # Contagem simples
        vitorias_t0 = r.count(0)
        vitorias_t1 = r.count(1)
        
        # REGRA 1: Vitória simples (2x0)
        if vitorias_t0 == 2: venc_mao_int = 0
        elif vitorias_t1 == 2: venc_mao_int = 1
        
        # REGRA 2: Primeira rodada empatou (Canga na 1ª)
        # Regra: Quem ganhar a 2ª, LEVA A MÃO.
        elif r[0] == -1:
            if len(r) >= 2 and r[1] != -1:
                venc_mao_int = r[1] # <--- AQUI O FIX: Acaba na 2ª rodada!
            elif len(r) == 3 and r[1] == -1 and r[2] != -1:
                venc_mao_int = r[2] # 1ª e 2ª empataram, quem levar a 3ª ganha.
            elif len(r) == 3 and r[1] == -1 and r[2] == -1:
                venc_mao_int = -2 # 3 empates (ninguém ganha ou ganha o mão, escolhi anular)

        # REGRA 3: Primeira teve vencedor, mas a 2ª empatou
        # Regra: Quem ganhou a 1ª LEVA A MÃO.
        elif len(r) >= 2 and r[1] == -1 and r[0] != -1:
            venc_mao_int = r[0] # <--- FIX: Acaba na 2ª rodada se ela empatar!

        # REGRA 4: 1ª e 2ª tiveram vencedores diferentes (1x1), decide na 3ª
        elif len(r) == 3 and r[2] == -1:
            # Se a 3ª empatar, a regra oficial diz que ganha quem venceu a 1ª
            if r[0] != -1: venc_mao_int = r[0]

        sala['mao'].vencedor_mao = venc_mao_int
        
        # --- 3. EXECUÇÃO DO RESULTADO ---
        if sala['mao'].vencedor_mao is not None:
             # Mão encerrada
             sala['mesa_cartas'] = []
             await enviar_estado_mesa(nome_sala)
             await finalizar_mao(nome_sala, sala['mao'].vencedor_mao)
        else:
            # Continua para a próxima rodada
            await notificar_info_jogo(nome_sala)
            for p in sala['jogadores']:
                if not p.startswith('BOT'):
                    await sio.emit('resultado_rodada', {'vencedor': vencedor_txt}, to=p)
            
            sala['mesa_cartas'] = []
            await enviar_estado_mesa(nome_sala)
            
            sala['vez_atual_idx'] = proximo_a_jogar
            await atualizar_turnos(nome_sala)

async def iniciar_nova_mao(nome_sala):
    if nome_sala not in jogos: return
    sala = jogos[nome_sala]
    
    if 'valor_proposto_temp' in sala: del sala['valor_proposto_temp']
    if 'pedinte_temp' in sala: del sala['pedinte_temp']

    jogo = sala['jogo']
    sala['mao'] = Mao(jogo)
    sala['mao'].dono_atual_da_aposta = None 
    
    sala['mesa_cartas'] = []; sala['maos_server'] = [] 
    
    num_p = sala['max_jogadores']
    maos, vira = jogo.dar_cartas(num_jogadores=num_p)
    sala['maos_server'] = maos 

    if 'jogador_inicial_mao' not in sala: sala['jogador_inicial_mao'] = -1
    sala['jogador_inicial_mao'] = (sala['jogador_inicial_mao'] + 1) % num_p
    sala['vez_atual_idx'] = sala['jogador_inicial_mao']

    placar = sala['placar']
    time_11 = -1
    eh_ferro = (placar[0] == 11 and placar[1] == 11)
    
    sala['estado_jogo'] = 'JOGANDO'
    
    if placar[0] == 11 and not eh_ferro: time_11 = 0; sala['estado_jogo'] = 'MAO_DE_11'
    elif placar[1] == 11 and not eh_ferro: time_11 = 1; sala['estado_jogo'] = 'MAO_DE_11'

    for p in sala['jogadores']: 
        if not p.startswith('BOT'): await sio.emit('atualizar_mesa', {'cartas': []}, to=p)
    await emitir_som(nome_sala, 'shuffle')

    for i, p_sid in enumerate(sala['jogadores']):
        if p_sid.startswith('BOT'): continue
        cartas_json = [{'valor': c.valor, 'naipe': c.naipe} for c in maos[i]]
        vira_json = {'valor': vira.valor, 'naipe': vira.naipe}
        blind = False
        await sio.emit('receber_mao', {
            'minhas_cartas': cartas_json, 'vira': vira_json, 
            'animar': True, 'blind': blind, 'seu_indice': i, 'modo_jogo': num_p
        }, to=p_sid)
        
        if time_11 != -1 and (i % 2) == time_11:
            idx_parc = (i + 2) % num_p
            cartas_visualizar = []
            msg_titulo = ""
            if num_p == 2:
                cartas_visualizar = [{'valor': c.valor, 'naipe': c.naipe} for c in maos[i]]
                msg_titulo = "JOGAR A MÃO DE 11?"
            else:
                cartas_visualizar = [{'valor': c.valor, 'naipe': c.naipe} for c in maos[idx_parc]]
                msg_titulo = "CARTAS DO PARCEIRO"

            vira_json = {'valor': vira.valor, 'naipe': vira.naipe}
            await sio.emit('decisao_mao_11', {
                'cartas_parceiro': cartas_visualizar, 
                'vira': vira_json, 
                'titulo': msg_titulo 
            }, to=p_sid)

    if sala['estado_jogo'] == 'MAO_DE_11':
        jogs_decisao = [j for k, j in enumerate(sala['jogadores']) if k % 2 == time_11]
        if all(j.startswith('BOT') for j in jogs_decisao):
            sala['estado_jogo'] = 'JOGANDO'; sala['mao'].valor_atual = 3

    await notificar_info_jogo(nome_sala)
    
    if sala['estado_jogo'] == 'JOGANDO':
        await atualizar_turnos(nome_sala)
    else:
        for p in sala['jogadores']:
            if not p.startswith('BOT'): await sio.emit('status_vez', {'e_sua_vez': False}, to=p)

async def finalizar_mao(nome_sala, ganhador_dado):
    if nome_sala not in jogos: return
    sala = jogos[nome_sala]
    pontos = sala['mao'].valor_atual
    
    time_venc = 0 # Valor padrão (só usado se tudo falhar, mas não vai falhar)
    
    # 1. Se receber Inteiro (0 ou 1), confia nele.
    if isinstance(ganhador_dado, int):
        time_venc = ganhador_dado % 2
    
    # 2. Se receber String (fallback), analisa o conteúdo.
    elif isinstance(ganhador_dado, str):
        texto = ganhador_dado.upper()
        # Se tiver "1", "B", ou "TIME 1", é o Time 1.
        if "1" in texto or "B" in texto:
            time_venc = 1
        else:
            time_venc = 0
            
    # Aplica os pontos no array do placar (índice 0 ou 1)
    sala['placar'][time_venc] += pontos
    print(f"[DEBUG] VENCEDOR MAO: Time {time_venc} (Pontos: {pontos})")

    # Verifica se alguém fechou o SET (12 pontos)
    if max(sala['placar']) >= 12:
        idx_set_winner = 0 if sala['placar'][0] >= 12 else 1
        
        if 'sets' not in sala: sala['sets'] = [0, 0]
        sala['sets'][idx_set_winner] += 1
        sala['placar'] = [0, 0] 
        
        if sala['sets'][idx_set_winner] >= 2:
            win_team_letra = "A" if idx_set_winner == 0 else "B"
            for i, p in enumerate(sala['jogadores']):
                if p.startswith('BOT'): continue
                meu_time = i % 2
                eh_vitoria = (meu_time == idx_set_winner)
                msg = "VITÓRIA! CAMPEÃO!" if eh_vitoria else "DERROTA! FIM DE JOGO!"
                snd = 'win' if eh_vitoria else 'lose'
                await sio.emit('fim_de_jogo', {
                    'titulo': msg, 
                    'motivo': f"Time {win_team_letra} venceu a partida!", 
                    'placar': [0,0], 
                    'som': snd
                }, to=p)
            sala['sets'] = [0, 0]; sala['estado_jogo'] = 'FIM'
        else:
            # Fim de Set
            placar_sets = f"{sala['sets'][0]} x {sala['sets'][1]}"
            msg = f"FIM DA PARTIDA! Time {'A' if idx_set_winner==0 else 'B'} venceu o Set.\nSETS: {placar_sets}"
            for i, p in enumerate(sala['jogadores']):
                if not p.startswith('BOT'):
                    await sio.emit('mensagem', msg, to=p)
                    som = 'win' if (i%2) == idx_set_winner else 'lose'
                    await sio.emit('tocar_som', {'som': som}, to=p)
            await asyncio.sleep(4)
            await iniciar_nova_mao(nome_sala)
    else:
        # Fim de Mão Normal
        nome_exibir = "Time A" if time_venc == 0 else "Time B"
        for p in sala['jogadores']:
            if not p.startswith('BOT'):
                await sio.emit('fim_de_mao', {
                    'ganhador': nome_exibir, 
                    'ganhador_idx': time_venc,
                    'pontos': pontos
                }, to=p)
        await asyncio.sleep(3)
        await iniciar_nova_mao(nome_sala)


# ==============================================================================
# 3. TRUCO E INTERAÇÕES
# ==============================================================================

async def bot_responder_truco(nome_sala, idx_bot, valor_proposto):
    await asyncio.sleep(2.0)
    if nome_sala not in jogos: return
    aceitar = random.choice([True, False, True]) 
    sid_bot = jogos[nome_sala]['jogadores'][idx_bot]
    if aceitar: await responder_truco_logica(nome_sala, sid_bot, 'ACEITAR')
    else: await responder_truco_logica(nome_sala, sid_bot, 'CORRER')

async def responder_truco_logica(nome_sala, sid, resposta, dados_extras=None):
    sala = jogos[nome_sala]
    
    if resposta == 'ACEITAR':
        if 'valor_proposto_temp' in sala:
            sala['mao'].valor_atual = sala['valor_proposto_temp']
        else:
            vals = {1:3, 3:6, 6:9, 9:12, 12:12}
            sala['mao'].valor_atual = vals.get(sala['mao'].valor_atual, 3)
        
        pedinte_idx = sala.get('pedinte_temp', None)
        if pedinte_idx is not None:
            sala['mao'].dono_atual_da_aposta = pedinte_idx
            
        sala['estado_jogo'] = 'JOGANDO' 
        if 'valor_proposto_temp' in sala: del sala['valor_proposto_temp']
        if 'pedinte_temp' in sala: del sala['pedinte_temp']

        for p in sala['jogadores']:
            if not p.startswith('BOT'): 
                await sio.emit('truco_respondido', {'msg': f'ACEITOU! VALE {sala["mao"].valor_atual}'}, to=p)
        
        await notificar_info_jogo(nome_sala)
        await atualizar_turnos(nome_sala) 

    elif resposta == 'CORRER':
        await emitir_som(nome_sala, get_som_aleatorio(SONS_CORRER))
        idx = sala['jogadores'].index(sid)
        idx_vencedor = 1 if (idx % 2) == 0 else 0
        await finalizar_mao(nome_sala, idx_vencedor)
        
    elif resposta == 'AUMENTAR':
        # Confirma o valor anterior
        if 'valor_proposto_temp' in sala:
            sala['mao'].valor_atual = sala['valor_proposto_temp']

        pedinte_original_idx = sala.get('pedinte_temp')
        repicador_idx = sala['jogadores'].index(sid)

        # Leitura segura do valor
        val_recebido = 0
        if dados_extras:
            val_recebido = dados_extras.get('novo_valor') or dados_extras.get('valor') or 0

        if not val_recebido:
            atual = sala['mao'].valor_atual
            if atual == 3:
                val_recebido = 6
            elif atual == 6:
                val_recebido = 9
            elif atual == 9:
                val_recebido = 12

        novo_valor = int(val_recebido)

        # Som do aumento (se quiser variações, coloque seis1/nove1/doze1 nas listas)
        som_aumento = None
        if novo_valor == 6:
            som_aumento = get_som_aleatorio(SONS_SEIS)
        elif novo_valor == 9:
            som_aumento = get_som_aleatorio(SONS_NOVE)
        elif novo_valor == 12:
            som_aumento = get_som_aleatorio(SONS_DOZE)

        if som_aumento:
            await emitir_som(nome_sala, som_aumento)

        sala['valor_proposto_temp'] = novo_valor
        sala['pedinte_temp'] = repicador_idx
        sala['estado_jogo'] = 'TRUCO'

        nome_repicador = sala['jogadores_nomes'][repicador_idx]
        sid_alvo = sala['jogadores'][pedinte_original_idx]

        if sid_alvo.startswith('BOT'):
            asyncio.create_task(bot_responder_truco(nome_sala, pedinte_original_idx, novo_valor))
        else:
            await sio.emit(
                'receber_pedido_truco',
                {'valor': novo_valor, 'quem_pediu': nome_repicador},
                to=sid_alvo
            )
    
@sio.event
async def pedir_truco(sid, dados):
    n = dados['nome_sala']
    sala = jogos[n]
    ultimos_sinais[sid] = time.time()
    
    # Validações
    if sala['estado_jogo'] != 'JOGANDO' or 11 in sala['placar']: return
    idx = sala['jogadores'].index(sid)
    if sala['vez_atual_idx'] != idx: return 
    try:
        pode, msg = sala['mao'].pode_pedir_aumento(idx)
        if not pode: return 
    except: pass
    
    sala['estado_jogo'] = 'TRUCO'
    sala['pedinte_temp'] = idx
    sala['valor_proposto_temp'] = dados['valor']
    
    # --- BLOCO DE SOM (SUBSTITUIR) ---
    som_escolhido = get_som_aleatorio(SONS_TRUCO)
    val = int(dados['valor'])

    if val == 6:
        som_escolhido = get_som_aleatorio(SONS_SEIS)
    elif val == 9:
        som_escolhido = get_som_aleatorio(SONS_NOVE)
    elif val == 12:
        som_escolhido = get_som_aleatorio(SONS_DOZE)

    await emitir_som(n, som_escolhido)
# --------------------------------

    
  
    prox = (idx + 1) % sala['max_jogadores']
    sid_op = sala['jogadores'][prox]
    nome = sala['jogadores_nomes'][idx]
    
    if sid_op.startswith('BOT'): 
        asyncio.create_task(bot_responder_truco(n, prox, dados['valor']))
    else: 
        await sio.emit('receber_pedido_truco', {'valor': dados['valor'], 'quem_pediu': nome}, to=sid_op)
        await sio.emit('aguardando_truco', {}, to=sid)
@sio.event
async def responder_truco(sid, dados): 
    ultimos_sinais[sid] = time.time()
    await responder_truco_logica(dados['nome_sala'], sid, dados['resposta'], dados)

@sio.event
async def responder_mao_11(sid, dados):
    ultimos_sinais[sid] = time.time()
    n = dados['nome_sala']; sala = jogos[n]
    resposta = dados['resposta']
    if resposta == 'JOGAR':
        sala['mao'].valor_atual = 3
        sala['estado_jogo'] = 'JOGANDO'
        await notificar_info_jogo(n)
        await sio.emit('mensagem', "Mão de 11 ACEITA! Valendo 3!", room=n)
        await atualizar_turnos(n)
    elif resposta == 'CORRER':
        sala['mao'].valor_atual = 1
        idx = sala['jogadores'].index(sid)
        idx_vencedor = 1 if (idx % 2) == 0 else 0
        await finalizar_mao(n, idx_vencedor)

# ==============================================================================
# 4. EVENTOS DE CONEXÃO E SALAS
# ==============================================================================

async def enviar_lista_salas(sid=None):
    lista = [{'nome': n, 'qtd': len(d['jogadores']), 'max': d['max_jogadores']} for n, d in jogos.items()]
    msg = 'receber_lista_salas'
    if sid: await sio.emit(msg, lista, to=sid)
    else: await sio.emit(msg, lista)

async def gerenciar_desistencia(sid):
    sala_encontrada = None; nome_sala = None
    for nome, sala in jogos.items():
        if sid in sala['jogadores']:
            sala_encontrada = sala; nome_sala = nome; break
    if sala_encontrada:
        idx = sala_encontrada['jogadores'].index(sid)
        time_venc = 1 if (idx % 2) == 0 else 0
        for p in sala_encontrada['jogadores']:
            if isinstance(p, str) and not p.startswith('BOT') and p != sid:
                meu_time = sala_encontrada['jogadores'].index(p) % 2
                tit = "VITÓRIA (W.O.)!" if meu_time == time_venc else "DERROTA"
                await sio.emit('fim_de_jogo', {
                    'titulo': tit, 'motivo': 'Oponente desconectou.', 
                    'placar': sala_encontrada['placar'], 
                    'som': 'win' if meu_time==time_venc else 'lose'
                }, to=p)
        del jogos[nome_sala]
        await enviar_lista_salas()

@sio.event
async def connect(sid, environ): 
    ultimos_sinais[sid] = time.time()
    await enviar_lista_salas(sid)

@sio.event
async def disconnect(sid): 
    if sid in ultimos_sinais: del ultimos_sinais[sid]
    await gerenciar_desistencia(sid)

@sio.event
async def pedir_lista_salas(sid): await enviar_lista_salas(sid)

@sio.event
async def criar_sala_vs_bot(sid, d):
    ultimos_sinais[sid] = time.time()
    n = d['nome_sala']; modo = int(d.get('modo', 4))
    if n in jogos: return
    jogs = [sid] + [f'BOT_{i+1}' for i in range(modo-1)]
    nomes = [d['nome_jogador']] + [f'Robô {i+1}' for i in range(modo-1)]
    jogos[n] = {'jogo': TrucoGame(), 'mao': None, 'maos_server': [], 'jogadores': jogs, 'jogadores_nomes': nomes, 'mesa_cartas': [], 'placar': [0,0], 'sets': [0,0], 'vez_atual_idx': None, 'estado_jogo': 'JOGANDO', 'max_jogadores': modo}
    await sio.enter_room(sid, n)
    await iniciar_nova_mao(n)
    await enviar_lista_salas()

@sio.event
async def criar_sala(sid, d):
    ultimos_sinais[sid] = time.time()
    n = d['nome_sala']; modo = int(d['modo'])
    if n in jogos: return
    jogos[n] = {'jogo': TrucoGame(), 'mao': None, 'maos_server': [], 'jogadores': [sid], 'jogadores_nomes': [d['nome_jogador']], 'mesa_cartas': [], 'placar': [0,0], 'sets': [0,0], 'vez_atual_idx': None, 'estado_jogo': 'JOGANDO', 'max_jogadores': modo}
    await sio.enter_room(sid, n)
    await enviar_lista_salas()

@sio.event
async def entrar_sala(sid, d):
    ultimos_sinais[sid] = time.time()
    n = d['nome_sala']
    if n in jogos:
        s = jogos[n]
        if len(s['jogadores']) < s['max_jogadores']:
            s['jogadores'].append(sid); s['jogadores_nomes'].append(d['nome_jogador'])
            await sio.enter_room(sid, n)
            if len(s['jogadores']) == s['max_jogadores']: await iniciar_nova_mao(n)
            else: await sio.emit('mensagem', 'Aguardando...', to=sid)
            await enviar_lista_salas()
        else: await sio.emit('erro', 'Sala cheia', to=sid)

@sio.event
async def jogar_carta(sid, d):
    ultimos_sinais[sid] = time.time()
    n = d['nome_sala']; sala = jogos[n]
    idx = sala['jogadores'].index(sid)
    if sala['vez_atual_idx'] != idx: return
    mao = sala['maos_server'][idx]
    
    val_alvo = str(d['carta']['valor'])
    nai_alvo = str(d['carta']['naipe'])
    
    c_obj = next((c for c in mao if str(c.valor) == val_alvo and str(c.naipe) == nai_alvo), None)
    
    if c_obj:
        mao.remove(c_obj)
        await processar_jogada_carta(n, sid, c_obj)
    else:
        print(f"ERRO: Carta não encontrada! {val_alvo}/{nai_alvo}")

@sio.event
async def enviar_emote(sid, d):
    n = d['nome_sala']
    if n in jogos:
        idx = jogos[n]['jogadores'].index(sid)
        for p in jogos[n]['jogadores']: 
            if not p.startswith('BOT'): await sio.emit('receber_emote', {'remetente_idx': idx, 'conteudo': d['conteudo'], 'tipo': d['tipo']}, to=p)

@sio.event
async def sair_do_jogo(sid): await gerenciar_desistencia(sid)

sio.start_background_task(loop_monitoramento_afk)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)































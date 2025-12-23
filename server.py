import socketio
import asyncio
import random
import time
from truco_core import TrucoGame, Mao, Carta

# ==============================================================================
# CONFIGURAÇÕES INICIAIS (CORRIGIDO)
# ==============================================================================
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

# Lista de arquivos que o site precisa carregar
static_files = {
    '/': 'index.html',
    '/win.mp3': 'win.mp3',
    '/lose.mp3': 'lose.mp3',
    '/shuffle.mp3': 'shuffle.mp3',
    '/card.mp3': 'card.mp3',
    '/truco.mp3': 'truco.mp3',
    '/correr.mp3': 'correr.mp3'
}

app = socketio.ASGIApp(sio, static_files=static_files)

jogos = {}
ultimos_sinais = {} 
TEMPO_LIMITE_AFK = 30 

# ==============================================================================
# 1. MONITORAMENTO E UTILITÁRIOS
# ==============================================================================

async def loop_monitoramento_afk():
    print("[SISTEMA] Monitor de inatividade iniciado.")
    while True:
        await asyncio.sleep(1)
        agora = time.time()
        sids = list(ultimos_sinais.keys())
        for sid in sids:
            ultimo = ultimos_sinais.get(sid, agora)
            if agora - ultimo > TEMPO_LIMITE_AFK:
                print(f"[AFK] Removendo {sid}.")
                if sid in ultimos_sinais: del ultimos_sinais[sid]
                await gerenciar_desistencia(sid)
                try: await sio.disconnect(sid)
                except: pass

async def emitir_som(nome_sala, som):
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
            'nomes': sala['jogadores_nomes'], 'seu_indice': i
        }, to=p)

async def atualizar_turnos(nome_sala):
    sala = jogos[nome_sala]
    if sala['estado_jogo'] in ['MAO_DE_11', 'TRUCO', 'FIM']: return

    vez_idx = sala['vez_atual_idx']
    if vez_idx is not None:
        sid_vez = sala['jogadores'][vez_idx]
        for p_sid in sala['jogadores']:
            if not p_sid.startswith('BOT'):
                await sio.emit('status_vez', {'e_sua_vez': (p_sid == sid_vez)}, to=p_sid)
        if sid_vez.startswith('BOT'):
            asyncio.create_task(bot_jogar_delay(nome_sala, vez_idx))
    else:
        for p_sid in sala['jogadores']:
            if not p_sid.startswith('BOT'):
                await sio.emit('status_vez', {'e_sua_vez': False}, to=p_sid)

# ==============================================================================
# 2. LÓGICA DO JOGO (CORRIGIDO)
# ==============================================================================

async def bot_jogar_delay(nome_sala, idx_bot):
    await asyncio.sleep(1.5)
    if nome_sala not in jogos: return
    sala = jogos[nome_sala]
    if sala['vez_atual_idx'] != idx_bot: return 
    mao_bot = sala['maos_server'][idx_bot]
    if not mao_bot: return
    carta_escolhida = max(mao_bot, key=lambda c: sala['jogo'].calcular_forca(c))
    mao_bot.remove(carta_escolhida)
    sid_bot = sala['jogadores'][idx_bot]
    await processar_jogada_carta(nome_sala, sid_bot, carta_escolhida)

async def processar_jogada_carta(nome_sala, sid, carta_obj):
    if nome_sala not in jogos: return
    sala = jogos[nome_sala]
    
    sala['mesa_cartas'].append( (sid, carta_obj) )
    await emitir_som(nome_sala, 'card')
    await enviar_estado_mesa(nome_sala)

    num_p = sala['max_jogadores']
    
    # 1. Se ainda faltam jogadores jogarem na rodada
    if len(sala['mesa_cartas']) < num_p:
        sala['vez_atual_idx'] = (sala['vez_atual_idx'] + 1) % num_p
        await atualizar_turnos(nome_sala)
    
    # 2. Rodada completa
    else:
        sala['vez_atual_idx'] = None
        await atualizar_turnos(nome_sala) # Bloqueia UI
        await asyncio.sleep(1.5)
        
        # Calcular vencedor da rodada
        maior = -1; idx_venc = -1
        try:
            for item in sala['mesa_cartas']:
                sid_j, c = item
                f = sala['jogo'].calcular_forca(c)
                if f > maior:
                    maior = f
                    if sid_j in sala['jogadores']:
                        idx_venc = sala['jogadores'].index(sid_j)
                elif f == maior: pass 
        except Exception as e:
            print(f"Erro calculo vencedor: {e}"); idx_venc = 0

        time_vencedor_rodada = idx_venc % 2
        sala['mao'].rodadas.append(time_vencedor_rodada)
        
        # Lógica Melhor de 3
        vitorias_t0 = sala['mao'].rodadas.count(0)
        vitorias_t1 = sala['mao'].rodadas.count(1)
        
        vencedor_mao = None
        if vitorias_t0 >= 2: vencedor_mao = "Time 0"
        elif vitorias_t1 >= 2: vencedor_mao = "Time 1"
        elif len(sala['mao'].rodadas) == 3:
             vencedor_mao = f"Time {time_vencedor_rodada}" # 3ª rodada quem ganha leva
        
        sala['mao'].vencedor_mao = vencedor_mao
        
        for p in sala['jogadores']:
            if not p.startswith('BOT'):
                await sio.emit('resultado_rodada', {'vencedor': f"Time {time_vencedor_rodada}"}, to=p)
        
        # LIMPEZA IMPORTANTE ANTES DE DECIDIR FLUXO
        sala['mesa_cartas'] = []
        await enviar_estado_mesa(nome_sala)
        
        if not sala['mao'].vencedor_mao:
            # Continua na mesma mão
            sala['vez_atual_idx'] = idx_venc
            await atualizar_turnos(nome_sala)
        else:
            # Fim da mão (alguém ganhou 2 rodadas)
            await finalizar_mao(nome_sala, sala['mao'].vencedor_mao)

async def iniciar_nova_mao(nome_sala):
    if nome_sala not in jogos: return
    sala = jogos[nome_sala]
    
    # Limpeza de estados temporários
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
    
    # Define estado padrão como JOGANDO
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
        blind = True if eh_ferro else False
        await sio.emit('receber_mao', {
            'minhas_cartas': cartas_json, 'vira': vira_json, 
            'animar': True, 'blind': blind, 'seu_indice': i, 'modo_jogo': num_p
        }, to=p_sid)
        
        if time_11 != -1 and (i % 2) == time_11:
            idx_parc = (i + 2) % num_p
            cp = [{'valor': c.valor, 'naipe': c.naipe} for c in maos[idx_parc]]
            await sio.emit('decisao_mao_11', {'cartas_parceiro': cp}, to=p_sid)

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

async def finalizar_mao(nome_sala, ganhador_str):
    sala = jogos[nome_sala]
    pontos = sala['mao'].valor_atual
    
    try: time_venc = int(ganhador_str.split(" ")[1])
    except: time_venc = 0

    sala['placar'][time_venc] += pontos
    
    # Verifica fim de SET (12 pontos)
    if max(sala['placar']) >= 12:
        idx_set_winner = 0 if sala['placar'][0] >= 12 else 1
        
        if 'sets' not in sala: sala['sets'] = [0, 0]
        sala['sets'][idx_set_winner] += 1
        sala['placar'] = [0, 0] 
        
        # MELHOR DE 3 SETS
        if sala['sets'][idx_set_winner] >= 2:
            win_team = "Time 0" if idx_set_winner == 0 else "Time 1"
            
            for i, p in enumerate(sala['jogadores']):
                if p.startswith('BOT'): continue
                
                meu_time = "Time 0" if (i % 2 == 0) else "Time 1"
                eh_vitoria = (meu_time == win_team)
                
                msg = "VITÓRIA! CAMPEÃO!" if eh_vitoria else "DERROTA! FIM DE JOGO!"
                sub = f"Placar Final de Sets: {sala['sets'][0]} x {sala['sets'][1]}"
                snd = 'win' if eh_vitoria else 'lose'
                
                await sio.emit('fim_de_jogo', {
                    'titulo': msg, 
                    'motivo': sub, 
                    'placar': [0,0], 
                    'som': snd
                }, to=p)
            
            sala['sets'] = [0, 0] 
            sala['mesa_cartas'] = [] 
            sala['estado_jogo'] = 'FIM'
            
        else:
            placar_sets = f"{sala['sets'][0]} x {sala['sets'][1]}"
            msg = f"FIM DA PARTIDA! Time {idx_set_winner} venceu o Set.\nSETS: {placar_sets}"
            
            for i, p in enumerate(sala['jogadores']):
                if not p.startswith('BOT'):
                    await sio.emit('mensagem', msg, to=p)
                    meu_time = i % 2
                    som = 'win' if meu_time == idx_set_winner else 'lose'
                    await sio.emit('tocar_som', {'som': som}, to=p)
            
            await asyncio.sleep(4)
            await iniciar_nova_mao(nome_sala)

    else:
        # Fim normal da mão
        for p in sala['jogadores']:
            if not p.startswith('BOT'):
                await sio.emit('fim_de_mao', {'ganhador': ganhador_str, 'pontos': pontos}, to=p)
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
        await notificar_info_jogo(nome_sala)
        await atualizar_turnos(nome_sala) 
        
        if 'valor_proposto_temp' in sala: del sala['valor_proposto_temp']
        for p in sala['jogadores']:
            if not p.startswith('BOT'): 
                await sio.emit('truco_respondido', {'msg': f'ACEITOU! VALE {sala["mao"].valor_atual}'}, to=p)

    elif resposta == 'CORRER':
        idx = sala['jogadores'].index(sid)
        time_venc = 1 if (idx % 2) == 0 else 0
        await finalizar_mao(nome_sala, f"Time {time_venc}")
    
    elif resposta == 'AUMENTAR':
        pedinte_original_idx = sala.get('pedinte_temp')
        repicador_idx = sala['jogadores'].index(sid)
        novo_valor = dados_extras.get('novo_valor', 3) if dados_extras else 0
        sala['valor_proposto_temp'] = novo_valor 
        sala['pedinte_temp'] = repicador_idx 
        sala['estado_jogo'] = 'TRUCO' 
        nome_repicador = sala['jogadores_nomes'][repicador_idx]
        sid_alvo = sala['jogadores'][pedinte_original_idx] 
        if sid_alvo.startswith('BOT'):
            asyncio.create_task(bot_responder_truco(nome_sala, pedinte_original_idx, novo_valor))
        else:
            await sio.emit('receber_pedido_truco', {'valor': novo_valor, 'quem_pediu': nome_repicador}, to=sid_alvo)

    if resposta != 'AUMENTAR' and 'pedinte_temp' in sala: 
        del sala['pedinte_temp']
        if 'valor_proposto_temp' in sala: del sala['valor_proposto_temp']

@sio.event
async def pedir_truco(sid, dados):
    n = dados['nome_sala']; sala = jogos[n]
    ultimos_sinais[sid] = time.time()
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
    await emitir_som(n, 'truco')
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
        time_venc = 1 if (idx % 2) == 0 else 0
        await finalizar_mao(n, f"Time {time_venc}")

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
    c_obj = next((c for c in mao if c.valor == d['carta']['valor'] and c.naipe == d['carta']['naipe']), None)
    if c_obj:
        mao.remove(c_obj)
        await processar_jogada_carta(n, sid, c_obj)

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

# -*- coding: utf-8 -*-
"""
================================================================================
TURNOS FLEXIVEIS (15 min) - VERSAO CORRIGIDA
Escalonamento quinzenal (14 dias) com jornada de tempo integral fechada
--------------------------------------------------------------------------------
Ajustes desta versao em relacao a anterior:

(1) IGUALDADE NA JORNADA. Cada funcionario ATIVO trabalha EXATAMENTE a carga
    do ciclo (88 / 80 / 72 h em 14 dias = 44 / 40 / 36 h por semana), ou nao e
    ativado. Antes a carga era apenas um teto (<=); agora e fechada:
        sum_{d,p} (1/Q) w[i,d,p] = Hmax14 * a[i],   a[i] in {0,1}
    Isso modela contratos de tempo integral: o funcionario cumpre a jornada
    contratual cheia, distribuida de forma flexivel (blocos de 4-6h, jornada
    partida ate 10h/dia) ao longo do ciclo.

(2) PAGAMENTO POR HORA, SEM IRREDUTIBILIDADE. Divisor unico de 220 h/mes em
    todos os cenarios. Removido o segundo solve (irredutibilidade), que era a
    fonte das solucoes invalidas por estouro de tempo.

(3) ANTI-TIMEOUT. O modelo de atribuicao tem forte SIMETRIA (funcionarios
    intercambiaveis), o que impedia o branch-and-cut de fechar o gap mesmo
    tendo achado o otimo. Corrige-se com:
      - quebra de simetria  a[i] >= a[i+1]  (ativa primeiro os indices baixos);
      - minimizacao implicita do quadro (cada ativo custa a jornada cheia);
      - parametros Symmetry=2 e MIPFocus=1;
      - cobertura total como restricao dura + corte de quadro minimo;
      - MIPGap = 0,5% e TimeLimit folgado.

OBJETIVO DO EXPERIMENTO: sob pagamento estritamente horario e contratos de
tempo integral, medir o custo e, sobretudo, o NUMERO DE FUNCIONARIOS necessario
para cobrir a demanda em cada regime de jornada. Espera-se que a reducao de
jornada eleve pouco o custo horario, mas exija ampliar o quadro (criacao de
empregos).

PORTE: com 25 funcionarios (pool), 14 dias e granularidade de 15 min, o modelo
tem ~22 mil binarias e dezenas de milhares de restricoes -> requer LICENCA
COMPLETA do Gurobi. Para testes rapidos use QUARTOS_POR_HORA = 2 (30 min).
================================================================================
"""

import math
import json
import gurobipy as gp
from gurobipy import GRB

# ------------------------------------------------------------ configuracoes
QUARTOS_POR_HORA = 4          # 4 = 15 min (pedido); 2 = 30 min (teste rapido)
NDAYS  = 14
POOL   = 25                   # quadro disponivel (o modelo ativa o subconjunto otimo)
HORA_INI, HORA_FIM = 7, 23
MULT   = 1.10                 # fator de demanda calibrado

TIME_LIMIT = 3600             # s (folgado; com simetria quebrada fecha bem antes)
MIP_GAP    = 5e-3             # 0,5% (suficiente; evita degenerescencia residual)

# ------------------------------------------------------------ tempo / demanda
Q = QUARTOS_POR_HORA
HORAS = list(range(HORA_INI, HORA_FIM))
P_DIA = len(HORAS) * Q
DT    = 1.0 / Q

def hora_do_periodo(p):
    return HORAS[p // Q]

BASE_DEMAND = {7:3, 8:4, 9:5, 10:6, 11:7, 12:8, 13:7, 14:6, 15:5, 16:5,
               17:7, 18:9, 19:8, 20:4, 21:4, 22:3}
WEEK_FACTOR = [1.0, 1.0, 1.0, 1.0, 1.0, 1.3, 0.8]

def demanda(d, p):
    t = hora_do_periodo(p)
    return math.ceil(BASE_DEMAND[t] * WEEK_FACTOR[d % 7] * MULT)

# ------------------------------------------------------------ custos (por hora)
PISO_MENSAL = 1856.00
ENCARGOS    = 0.678
ADIC_NOTURNO = 0.20
DIVISOR     = 220             # pagamento por hora, sem irredutibilidade

def custo_hora():
    return PISO_MENSAL / DIVISOR * (1 + ENCARGOS)

def custo_periodo(p):
    fator = (1 + ADIC_NOTURNO) if hora_do_periodo(p) >= 22 else 1.0
    return DT * custo_hora() * fator

LAMBDA = 1000.0

# ------------------------------------------------------------ regras do turno
MAX_CONT  = 6 * Q             # bloco continuo <= 6 h
MIN_BLOCO = 2 * Q             # bloco minimo de 2 h
MIN_DIA   = 4 * Q             # >= 4 h/dia (se trabalha no dia)
MAX_DIA   = 10 * Q            # <= 10 h/dia (jornada partida)
MAX_BLOCOS = 2                # ate 2 blocos/dia (uma interrupcao)
INTERJORNADA_H = 11

# ------------------------------------------------------------ cenarios
# (rotulo, Hmax14 [h], Wmax [dias], descricao)
CENARIOS = [
    ("A", 88, 11, "A - 11x3 (equiv. 6x1, 44h/sem)"),
    ("B", 80, 10, "B - 10x4 (equiv. 5x2, 40h/sem)"),
    ("D", 72,  9, "D - 9x5 (equiv. 4x3, 36h/sem)"),
]

def pares_interjornada():
    pares = []
    for p in range(P_DIA):
        fim_p = HORA_INI + (p + 1) * DT
        for q in range(P_DIA):
            ini_q = HORA_INI + q * DT
            if (24 - fim_p) + ini_q < INTERJORNADA_H:
                pares.append((p, q))
    return pares

PARES_IJ = pares_interjornada()

# ------------------------------------------------------------ modelo
def resolver(hmax14, wmax, label="", pool=POOL,
             time_limit=TIME_LIMIT, mip_gap=MIP_GAP, verbose=True):
    EMP = range(pool)
    per_hmax = int(round(hmax14 * Q))      # numero de periodos exigidos por ativo

    m = gp.Model(f"FLEX_{label}")
    m.Params.OutputFlag = 1 if verbose else 0
    m.Params.TimeLimit  = time_limit
    m.Params.MIPGap     = mip_gap
    m.Params.Symmetry   = 2                # quebra de simetria agressiva
    m.Params.MIPFocus   = 1                # achar boas solucoes rapido (modelo degenerado)

    w  = m.addVars(EMP, range(NDAYS), range(P_DIA), vtype=GRB.BINARY, name="w")
    wk = m.addVars(EMP, range(NDAYS), vtype=GRB.BINARY, name="wk")
    a  = m.addVars(EMP, vtype=GRB.BINARY, name="a")          # funcionario ativo
    s  = m.addVars(EMP, range(NDAYS), range(P_DIA), lb=0.0, name="s")
    u  = m.addVars(range(NDAYS), range(P_DIA), lb=0.0, name="u")
    # cobertura total OBRIGATORIA (jornada fechada -> problema e de quantos
    # funcionarios contratar; nao se "compra" subcobertura). u fica como folga
    # tecnica fixada em 0; se o pool for insuficiente o modelo fica infactivel.
    for d in range(NDAYS):
        for p in range(P_DIA):
            u[d, p].UB = 0.0

    m.setObjective(
        gp.quicksum(custo_periodo(p) * w[i, d, p]
                    for i in EMP for d in range(NDAYS) for p in range(P_DIA))
        + LAMBDA * gp.quicksum(u[d, p] * DT
                               for d in range(NDAYS) for p in range(P_DIA)),
        GRB.MINIMIZE)

    # (R1) cobertura da demanda
    for d in range(NDAYS):
        for p in range(P_DIA):
            m.addConstr(gp.quicksum(w[i, d, p] for i in EMP) + u[d, p]
                        >= demanda(d, p), name=f"cob_{d}_{p}")

    # (corte valido) numero minimo de ativos = ceil(demanda_total / Hmax14):
    # como cada ativo entrega exatamente Hmax14 horas, sao necessarios pelo
    # menos esse numero para cobrir a demanda total. Acelera muito o B&C.
    dem_total = sum(demanda(d, p) for d in range(NDAYS) for p in range(P_DIA)) * DT
    n_min = math.ceil(dem_total / hmax14)
    m.addConstr(gp.quicksum(a[i] for i in EMP) >= n_min, name="quadro_minimo")

    for i in EMP:
        # (C0) IGUALDADE: carga do ciclo = Hmax14 se ativo, 0 se nao
        m.addConstr(gp.quicksum(w[i, d, p] for d in range(NDAYS) for p in range(P_DIA))
                    == per_hmax * a[i], name=f"jornada_{i}")
        # (C2) maximo de dias trabalhados (so se ativo)
        m.addConstr(gp.quicksum(wk[i, d] for d in range(NDAYS)) <= wmax * a[i])
        for d in range(NDAYS):
            # vinculo dia/ativo e jornada diaria
            m.addConstr(gp.quicksum(w[i, d, p] for p in range(P_DIA)) <= MAX_DIA * wk[i, d])
            m.addConstr(gp.quicksum(w[i, d, p] for p in range(P_DIA)) >= MIN_DIA * wk[i, d])
            # bloco continuo <= 6h
            for p in range(P_DIA - MAX_CONT):
                m.addConstr(gp.quicksum(w[i, d, p + k] for k in range(MAX_CONT + 1)) <= MAX_CONT)
            # inicio de bloco, bloco minimo de 2h
            for p in range(P_DIA):
                prev = w[i, d, p - 1] if p > 0 else 0
                m.addConstr(s[i, d, p] >= w[i, d, p] - prev)
                if p + MIN_BLOCO <= P_DIA:
                    m.addConstr(gp.quicksum(w[i, d, p + k] for k in range(MIN_BLOCO))
                                >= MIN_BLOCO * (w[i, d, p] - prev))
            # no maximo 2 blocos/dia
            m.addConstr(gp.quicksum(s[i, d, p] for p in range(P_DIA)) <= MAX_BLOCOS)
        # (C3) interjornada de 11h
        for d in range(NDAYS - 1):
            for (p, q) in PARES_IJ:
                m.addConstr(w[i, d, p] + w[i, d + 1, q] <= 1)
        # (C4) QUEBRA DE SIMETRIA: ativa primeiro os indices baixos
        if i < pool - 1:
            m.addConstr(a[i] >= a[i + 1])

    m.optimize()

    if m.SolCount == 0:
        return {"label": label, "status": int(m.Status), "sem_solucao": True}

    ativos = int(round(sum(a[i].X for i in EMP)))
    horas  = sum(w[i, d, p].X for i in EMP for d in range(NDAYS) for p in range(P_DIA)) * DT
    custo  = sum(custo_periodo(p) * w[i, d, p].X
                 for i in EMP for d in range(NDAYS) for p in range(P_DIA))
    under  = sum(u[d, p].X for d in range(NDAYS) for p in range(P_DIA)) * DT
    dem_tot = sum(demanda(d, p) for d in range(NDAYS) for p in range(P_DIA)) * DT
    sobre  = horas - (dem_tot - under)
    return {
        "label": label, "hmax14": hmax14, "wmax": wmax,
        "funcionarios_ativos": ativos,
        "custo_mo": custo, "horas_pagas": horas,
        "subcobertura": under, "sobrecobertura": sobre,
        "demanda_total_ph": dem_tot,
        "n_vars": m.NumVars, "n_bin": m.NumBinVars, "n_constrs": m.NumConstrs,
        "runtime": m.Runtime, "mip_gap": m.MIPGap, "status": int(m.Status),
    }

# ------------------------------------------------------------ execucao
def main():
    print("=" * 78)
    print(f"TURNOS FLEXIVEIS (jornada fechada) | {int(60/Q)} min | {NDAYS} dias | "
          f"pool {POOL} | pagamento horario (div. {DIVISOR})")
    print("=" * 78)
    dem_tot = sum(demanda(d, p) for d in range(NDAYS) for p in range(P_DIA)) * DT
    print(f"Demanda total do ciclo: {dem_tot:.0f} pessoas-hora | custo-hora R$ {custo_hora():.2f}\n")

    resultados = {}
    for key, hmax14, wmax, desc in CENARIOS:
        print("-" * 78)
        print(f"Cenario {desc}")
        r = resolver(hmax14, wmax, label=desc)
        resultados[key] = r
        if not r.get("sem_solucao"):
            print(f"  -> ativos={r['funcionarios_ativos']}  custo=R$ {r['custo_mo']:.2f}  "
                  f"horas={r['horas_pagas']:.1f}  subcob={r['subcobertura']:.1f}ph  "
                  f"sobrecob={r['sobrecobertura']:.1f}ph  gap={r['mip_gap']*100:.2f}%  "
                  f"t={r['runtime']:.0f}s")

    with open("resultados_flexivel_jornada_fechada.json", "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=1, ensure_ascii=False)

    print("\n" + "=" * 78)
    print("RESUMO - pagamento horario, contratos de tempo integral")
    print("=" * 78)
    print(f"{'Cenario':<34}{'Ativos':>8}{'Horas':>9}{'Custo (R$)':>14}{'vs A':>9}")
    base = resultados["A"].get("custo_mo")
    for key, _, _, desc in CENARIOS:
        r = resultados[key]
        if r.get("sem_solucao"):
            continue
        var = 100 * (r["custo_mo"] / base - 1) if base else 0.0
        print(f"{desc:<34}{r['funcionarios_ativos']:>8}{r['horas_pagas']:>9.0f}"
              f"{r['custo_mo']:>14.2f}{('%+.1f%%' % var):>9}")
    print("\nResultados salvos em resultados_flexivel_jornada_fechada.json")


if __name__ == "__main__":
    main()

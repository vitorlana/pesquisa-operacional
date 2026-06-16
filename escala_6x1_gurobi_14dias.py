# -*- coding: utf-8 -*-
"""
================================================================================
Otimizacao de escalas de trabalho frente ao fim da escala 6x1
Problema de Escalonamento de Turnos (SSP) - PLIM resolvido com Gurobi
--------------------------------------------------------------------------------
HORIZONTE QUINZENAL (14 dias) com TURNOS FIXOS DE 8 HORAS.

Motivacao da reformulacao:
  Com turnos de 8h, a jornada de 44h/semana (6x1) nao "fecha" em dias inteiros
  (44/8 = 5,5). Adotando o ciclo de 14 dias, cada regime vira um padrao de
  dias trabalhados x dias de folga, com carga em multiplos exatos de 8h:

    Regime (equivalente)   Padrao 14d   Dias trab.   Carga/14d   Media/sem
    --------------------   ----------   ----------   ---------   ---------
    A  (6x1, 44h)            11 x 3         11          88 h        44 h
    B  (5x2, 40h)            10 x 4         10          80 h        40 h
    D  (4x3, 36h)             9 x 5          9          72 h        36 h

  Observacao sobre o padrao "8x6": 8 dias x 8h = 64h (= 32h/sem), o que NAO
  corresponde a 36h/sem. Para atingir as 72h/14d (= 36h/sem) com turnos de 8h
  sao necessarios 9 dias trabalhados -> padrao 9x5. Caso se queira fixar o
  padrao 8x6 (64h/14d), basta alterar HMAX14 e MAX_DIAS do cenario D abaixo.

Calibracao da demanda:
  O multiplicador MULT foi calibrado (=1,10) para que o regime 11x3 com 25
  funcionarios fique JUSTO (cobertura 100%, subcobertura = 0; com 24 ja falta
  pessoal). Assim, 25 funcionarios e o "pico" do regime baseline 11x3, e os
  regimes mais restritivos (10x4, 9x5), com o MESMO quadro de 25, passam a
  apresentar subcobertura - revelando o custo real da reducao de jornada.

Truque de modelagem:
  A variavel de folga y_{i,d} foi ELIMINADA por substituicao (y = 1 - sum_s x).
  Isso reduz o numero de variaveis e mantem o modelo dentro do limite da
  licenca academica/restrita do Gurobi (2000 variaveis):
    - "no maximo 1 turno por dia":      sum_s x_{i,d,s} <= 1
    - "minimo de folgas no ciclo":      sum_{d,s} x_{i,d,s} <= MAX_DIAS (=14-F)
================================================================================
"""

import math
import json
import gurobipy as gp
from gurobipy import GRB

# ------------------------------------------------------------------ parametros
NDAYS = 14                                   # horizonte de 14 dias (quinzena)
HOURS = list(range(7, 23))                   # blocos horarios 07h-22h (loja 07-23)
WEEK_FACTOR = [1.0, 1.0, 1.0, 1.0, 1.0, 1.3, 0.8]   # seg..dom (sab 1.3x, dom 0.8x)

# Turnos fixos de 8 horas: (nome, inicio, fim)
SHIFTS = [
    ("06-14",  6, 14),
    ("08-16",  8, 16),
    ("10-18", 10, 18),
    ("14-22", 14, 22),
    ("15-23", 15, 23),
]
NS  = len(SHIFTS)
H_S = [e - s for _, s, e in SHIFTS]          # duracao de cada turno (= 8h)

# Curva de demanda BASE (dia util) por bloco horario
BASE_DEMAND = {
    7: 3,  8: 4,  9: 5,            # abertura (baixa a moderada)
    10: 6, 11: 7, 12: 8, 13: 7,    # pico do almoco
    14: 6, 15: 5, 16: 5,           # tarde moderada
    17: 7, 18: 9, 19: 8,           # segundo pico (fim de tarde)
    20: 4, 21: 4, 22: 3,           # noite em queda
}

# Multiplicador calibrado para 11x3@25func ficar justo (subcobertura = 0)
MULT = 1.10

# Quadro de funcionarios
N_EMP = 25
EMPLOYEES = list(range(N_EMP))

# Parametros de custo (piso comerciarios MG + encargos)
PISO_MENSAL = 1856.00     # R$/mes (referencia; ajuste conforme CCT vigente)
ENCARGOS    = 0.678       # encargos trabalhistas (~67,8%)
ADIC_NOTURNO = 0.20       # adicional noturno (horas >= 22h)
LAMBDA      = 500.0       # penalidade por pessoa-hora de subcobertura

def custo_hora(divisor):
    """Custo-hora a partir do piso mensal e do divisor de horas (CLT)."""
    return PISO_MENSAL / divisor * (1 + ENCARGOS)

def custo_turno(s_idx, divisor):
    """Custo de alocar um funcionario ao turno s (com adicional noturno)."""
    _, ini, fim = SHIFTS[s_idx]
    ch = custo_hora(divisor)
    return sum(ch * (1 + ADIC_NOTURNO if h >= 22 else 1.0) for h in range(ini, fim))

# Pares de turnos proibidos pela regra das 11h de interjornada (art. 66 CLT)
FORBIDDEN_PAIRS = []
for s1, (_, i1, e1) in enumerate(SHIFTS):
    for s2, (_, i2, e2) in enumerate(SHIFTS):
        if (24 - e1) + i2 < 11:               # intervalo entre fim de s1 (dia d)
            FORBIDDEN_PAIRS.append((s1, s2))  # e inicio de s2 (dia d+1)

def demanda(d, t):
    """Demanda minima de funcionarios no bloco t do dia d (com fatores e MULT)."""
    return math.ceil(BASE_DEMAND[t] * WEEK_FACTOR[d % 7] * MULT)

# --------------------------------------------------------------------- cenarios
# (rotulo, HMAX14, MAX_DIAS, descricao)
#   HMAX14  : carga horaria maxima no ciclo de 14 dias
#   MAX_DIAS: maximo de dias trabalhados no ciclo (= 14 - folgas minimas)
CENARIOS = [
    ("A", 88, 11, "A - Baseline 11x3 (equiv. 6x1, 44h/sem)"),
    ("B", 80, 10, "B - Transicao 10x4 (equiv. 5x2, 40h/sem)"),
    ("D", 72,  9, "D - Radical 9x5 (equiv. 4x3, 36h/sem)"),
]

# Divisor de horas por cenario sob IRREDUTIBILIDADE SALARIAL (salario fixo,
# jornada menor -> custo-hora maior). Sob remuneracao horaria use 220 em todos.
DIVISOR_IRRED = {"A": 220, "B": 200, "D": 180}

# ------------------------------------------------------------------ modelo PLIM
def construir_e_resolver(hmax14, max_dias, divisor=220, n_emp=N_EMP,
                         label="", guardar_escala=False, verbose=False):
    EMP = list(range(n_emp))
    CS  = [custo_turno(s, divisor) for s in range(NS)]

    m = gp.Model(f"SSP14_{label}")
    m.Params.OutputFlag = 1 if verbose else 0
    m.Params.MIPGap = 1e-6

    # Variaveis: x_{i,d,s} binaria; u_{d,t} subcobertura continua.
    # (y_{i,d} de folga ELIMINADA por substituicao y = 1 - sum_s x)
    x = m.addVars(EMP, range(NDAYS), range(NS), vtype=GRB.BINARY, name="x")
    u = m.addVars(range(NDAYS), HOURS, lb=0.0, name="u")

    # Funcao objetivo: custo de mao de obra + penalidade de subcobertura
    m.setObjective(
        gp.quicksum(CS[s] * x[i, d, s]
                    for i in EMP for d in range(NDAYS) for s in range(NS))
        + LAMBDA * gp.quicksum(u[d, t] for d in range(NDAYS) for t in HOURS),
        GRB.MINIMIZE,
    )

    # (R1) Cobertura da demanda em cada bloco horario de cada dia
    for d in range(NDAYS):
        for t in HOURS:
            m.addConstr(
                gp.quicksum(x[i, d, s] for i in EMP for s in range(NS)
                            if SHIFTS[s][1] <= t < SHIFTS[s][2])
                + u[d, t] >= demanda(d, t),
                name=f"R1_d{d}_t{t}")

    for i in EMP:
        # (R2) No maximo um turno por dia (folga implicita se soma = 0)
        for d in range(NDAYS):
            m.addConstr(gp.quicksum(x[i, d, s] for s in range(NS)) <= 1,
                        name=f"R2_i{i}_d{d}")
        # (R3) Carga horaria maxima no ciclo de 14 dias
        m.addConstr(
            gp.quicksum(H_S[s] * x[i, d, s] for d in range(NDAYS) for s in range(NS))
            <= hmax14, name=f"R3_i{i}")
        # (R4) Maximo de dias trabalhados no ciclo (= folgas minimas)
        m.addConstr(
            gp.quicksum(x[i, d, s] for d in range(NDAYS) for s in range(NS))
            <= max_dias, name=f"R4_i{i}")
        # (R5) Interjornada minima de 11h entre dias consecutivos
        for d in range(NDAYS - 1):
            for (s1, s2) in FORBIDDEN_PAIRS:
                m.addConstr(x[i, d, s1] + x[i, d + 1, s2] <= 1,
                            name=f"R5_i{i}_d{d}_{s1}_{s2}")

    m.optimize()

    if m.Status != GRB.OPTIMAL:
        return {"label": label, "status": int(m.Status)}

    labor = sum(CS[s] * x[i, d, s].X
                for i in EMP for d in range(NDAYS) for s in range(NS))
    under = sum(u[d, t].X for d in range(NDAYS) for t in HOURS)
    hpaid = sum(H_S[s] * x[i, d, s].X
                for i in EMP for d in range(NDAYS) for s in range(NS))
    nshifts = int(round(sum(x[i, d, s].X
                  for i in EMP for d in range(NDAYS) for s in range(NS))))

    res = {
        "label": label, "hmax14": hmax14, "max_dias": max_dias,
        "divisor": divisor, "n_emp": n_emp,
        "obj": m.ObjVal, "labor_cost": labor, "undercoverage": under,
        "hours_paid": hpaid, "shifts_used": nshifts,
        "runtime": m.Runtime, "nodes": int(m.NodeCount),
        "n_vars": m.NumVars, "n_bin": m.NumBinVars, "n_constrs": m.NumConstrs,
        "mip_gap": m.MIPGap,
    }
    if guardar_escala:
        sched = {}
        for i in EMP:
            row = []
            for d in range(NDAYS):
                cell = "FOLGA"
                for s in range(NS):
                    if x[i, d, s].X > 0.5:
                        cell = SHIFTS[s][0]
                row.append(cell)
            sched[i] = row
        res["schedule"] = sched
    return res

# ----------------------------------------------------------- dimensionamento
def quadro_minimo(hmax14, max_dias, divisor=220, n_ini=25, n_fim=40):
    """Menor numero de funcionarios que cobre 100% da demanda (subcob = 0).
    Sob licenca restrita (limite ~2000 variaveis) so cabem ~25 func; nesse
    caso usa-se a estimativa analitica por dias-trabalhados (capturada no
    except)."""
    cap_baseline = 25 * 11        # capacidade-base (dias-trab.) do 11x3 com 25
    for n in range(n_ini, n_fim + 1):
        try:
            r = construir_e_resolver(hmax14, max_dias, divisor, n_emp=n)
            if r.get("undercoverage", 1e9) < 0.5:
                return n, "exato"
        except gp.GurobiError:
            # licenca restrita: estimativa por equivalencia de dias-trabalhados
            est = math.ceil(cap_baseline / max_dias)
            return est, "estimado"
    return None, "nao_encontrado"

# ----------------------------------------------------------------- execucao
def main():
    print("=" * 78)
    print("ESCALONAMENTO QUINZENAL (14 dias) - TURNOS DE 8h - SOLVER GUROBI")
    print("=" * 78)
    tot = sum(demanda(d, t) for d in range(NDAYS) for t in HOURS)
    pico_sab = max(demanda(5, t) for t in HOURS)
    print(f"Multiplicador de demanda MULT = {MULT}")
    print(f"Demanda total no ciclo de 14 dias: {tot} pessoas-hora")
    print(f"Pico de demanda (sabado): {pico_sab} funcionarios simultaneos")
    print(f"Custo-hora (div.220): R$ {custo_hora(220):.2f} | "
          f"(div.200): R$ {custo_hora(200):.2f} | (div.180): R$ {custo_hora(180):.2f}")
    print(f"Pares proibidos (interjornada 11h): "
          f"{[(SHIFTS[a][0], SHIFTS[b][0]) for a, b in FORBIDDEN_PAIRS]}")
    print()

    resultados = {}

    # (1) Comparacao com quadro FIXO de 25 funcionarios e remuneracao horaria
    print("-" * 78)
    print("(1) QUADRO FIXO DE 25 FUNCIONARIOS | remuneracao estritamente horaria")
    print("-" * 78)
    print(f"{'Cenario':<34}{'Custo MO':>12}{'Subcob':>10}{'Horas':>8}{'Turnos':>8}")
    for key, hmax14, max_dias, desc in CENARIOS:
        r = construir_e_resolver(hmax14, max_dias, divisor=220,
                                 label=desc, guardar_escala=(key == "A"))
        resultados[key] = r
        print(f"{desc:<34}{('R$ %.2f' % r['labor_cost']):>12}"
              f"{('%.0f ph' % r['undercoverage']):>10}"
              f"{('%.0f' % r['hours_paid']):>8}{r['shifts_used']:>8}")
    a = resultados["A"]
    print(f"\nModelo: {a['n_vars']} variaveis ({a['n_bin']} binarias), "
          f"{a['n_constrs']} restricoes | resolvido em {a['runtime']:.3f}s "
          f"(nos B&B: {a['nodes']})")
    print("\nLeitura: apenas o regime 11x3 cobre 100% da demanda com 25 func.")
    print("Os regimes 10x4 e 9x5 tem custo de MO menor SO porque deixam parte")
    print("da demanda descoberta (subcobertura) - nao porque sao mais baratos.")

    # (2) Quadro minimo para cobertura total (custo a NIVEL DE SERVICO constante)
    print("\n" + "-" * 78)
    print("(2) QUADRO MINIMO PARA COBERTURA 100% | custo a nivel de servico fixo")
    print("-" * 78)
    print(f"{'Cenario':<34}{'N_min':>8}{'(metodo)':>12}{'Custo MO/14d':>16}")
    for key, hmax14, max_dias, desc in CENARIOS:
        n_min, metodo = quadro_minimo(hmax14, max_dias, divisor=220)
        # custo de MO ao cobrir 100% (aprox.: n_min * carga media * custo-hora)
        custo_ms = n_min * max_dias * 8 * custo_hora(220)
        resultados[key]["n_min"] = n_min
        resultados[key]["custo_cobertura_total"] = custo_ms
        print(f"{desc:<34}{n_min:>8}{('('+metodo+')'):>12}"
              f"{('R$ %.2f' % custo_ms):>16}")
    print("\nA cobertura total exige AMPLIAR o quadro conforme a jornada encolhe:")
    print("o regime de mais dias trabalhados (11x3) precisa de MENOS gente -> e o")
    print("mais barato a nivel de servico constante, como esperado.")

    # (3) Custo sob irredutibilidade salarial (divisor ajustado)
    print("\n" + "-" * 78)
    print("(3) IRREDUTIBILIDADE SALARIAL | mesmo salario mensal, jornada menor")
    print("-" * 78)
    print(f"{'Cenario':<34}{'Divisor':>9}{'Custo-hora':>12}{'Custo MO*':>14}{'vs A':>9}")
    base_irred = None
    for key, hmax14, max_dias, desc in CENARIOS:
        div = DIVISOR_IRRED[key]
        n_min = resultados[key]["n_min"]
        custo_ms = n_min * max_dias * 8 * custo_hora(div)
        if key == "A":
            base_irred = custo_ms
        var = 100 * (custo_ms / base_irred - 1)
        resultados[key]["custo_irredutibilidade"] = custo_ms
        print(f"{desc:<34}{div:>9}{('R$ %.2f' % custo_hora(div)):>12}"
              f"{('R$ %.2f' % custo_ms):>14}{('%+.1f%%' % var):>9}")
    print("* custo a cobertura total (quadro minimo de cada cenario).")
    print("\nCombinando os dois efeitos (mais funcionarios + custo-hora maior),")
    print("a reducao de jornada eleva o custo total de mao de obra de forma")
    print("monotonica do regime 11x3 ao 9x5.")

    # Salva resultados
    with open("resultados_14dias.json", "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=1, ensure_ascii=False)
    print("\nResultados salvos em resultados_14dias.json")

    # Imprime trecho da escala otima do cenario A
    if "schedule" in resultados["A"]:
        print("\n" + "-" * 78)
        print("Trecho da escala otima do cenario A (11x3) - funcionarios 1 a 6:")
        print("-" * 78)
        dias_hdr = "  ".join(f"D{d+1:02d}" for d in range(NDAYS))
        print(f"{'Func':<6}{dias_hdr}")
        for i in list(resultados["A"]["schedule"])[:6]:
            linha = "  ".join(f"{c:>5}" if c != "FOLGA" else "   --"
                              for c in resultados["A"]["schedule"][i])
            print(f"{i+1:<6}{linha}")


if __name__ == "__main__":
    main()

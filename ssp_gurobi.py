# -*- coding: utf-8 -*-
"""
Shift Scheduling Problem (SSP) - Otimizacao de escalas frente ao fim da 6x1
Modelo PLIM resolvido com Gurobi.
Cenarios: A (CLT 44h, 6x1), B (40h, 5x2), C (transicao gradual 43->40h),
          D (36h, 4x3).
"""
import json
import math
import gurobipy as gp
from gurobipy import GRB

# ---------------------------------------------------------------- dados
DAYS = list(range(7))                # 0=seg ... 5=sab, 6=dom
DAY_NAMES = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
HOURS = list(range(7, 23))           # blocos horarios 07h-22h (16 blocos)

# turnos: (nome, inicio, fim)
SHIFTS = [
    ("06-14", 6, 14),
    ("08-16", 8, 16),
    ("10-18", 10, 18),
    ("14-22", 14, 22),
    ("15-23", 15, 23),
]
NS = len(SHIFTS)
H_S = [e - s for _, s, e in SHIFTS]  # duracao = 8h em todos

EMPLOYEES = list(range(25))

# curva de demanda base (dias uteis), bloco t = hora cheia
BASE_DEMAND = {
    7: 3, 8: 4, 9: 5,            # abertura: baixa a moderada (3-5)
    10: 6, 11: 7, 12: 8, 13: 7,  # pico do almoco (6-8)
    14: 6, 15: 5, 16: 5,         # tarde moderada (4-6)
    17: 7, 18: 9, 19: 8,         # segundo pico (7-9)
    20: 4, 21: 4, 22: 3,         # noite em queda (3-4)
}
DAY_FACTOR = [1.0, 1.0, 1.0, 1.0, 1.0, 1.3, 0.8]

def demand(d, t):
    return math.ceil(BASE_DEMAND[t] * DAY_FACTOR[d])

# ---------------------------------------------------------------- custos
# Piso salarial comerciarios MG (CCT Fecomercio-MG) - valor de referencia
PISO_MENSAL = 1856.00          # R$/mes (referencia adotada no estudo)
SAL_HORA = PISO_MENSAL / 220   # divisor CLT de 220h
ENCARGOS = 0.678               # encargos trabalhistas (~67,8%)
CUSTO_HORA = SAL_HORA * (1 + ENCARGOS)
ADICIONAL_NOTURNO = 0.20       # sobre horas a partir das 22h

def shift_cost(s_idx):
    nome, ini, fim = SHIFTS[s_idx]
    horas_normais = 0
    horas_noturnas = 0
    for h in range(ini, fim):
        if h >= 22:
            horas_noturnas += 1
        else:
            horas_normais += 1
    return CUSTO_HORA * (horas_normais + horas_noturnas * (1 + ADICIONAL_NOTURNO))

C_S = [shift_cost(s) for s in range(NS)]
LAMBDA = 1000.0                # penalidade por unidade de subcobertura

# pares (s, s') proibidos pela regra das 11h de interjornada
FORBIDDEN_PAIRS = []
for s1, (_, i1, e1) in enumerate(SHIFTS):
    for s2, (_, i2, e2) in enumerate(SHIFTS):
        rest = (24 - e1) + i2     # fim de s1 no dia d ate inicio de s2 no dia d+1
        if rest < 11:
            FORBIDDEN_PAIRS.append((s1, s2))

# ---------------------------------------------------------------- modelo
def build_and_solve(hmax, fmin, label, save_schedule=False):
    m = gp.Model(f"SSP_{label}")
    m.Params.OutputFlag = 0
    m.Params.MIPGap = 1e-6

    x = m.addVars(EMPLOYEES, DAYS, range(NS), vtype=GRB.BINARY, name="x")
    y = m.addVars(EMPLOYEES, DAYS, vtype=GRB.BINARY, name="y")
    u = m.addVars(DAYS, HOURS, lb=0.0, name="u")

    # FO: custo de mao de obra + penalidade de subcobertura
    m.setObjective(
        gp.quicksum(C_S[s] * x[i, d, s] for i in EMPLOYEES for d in DAYS for s in range(NS))
        + LAMBDA * gp.quicksum(u[d, t] for d in DAYS for t in HOURS),
        GRB.MINIMIZE,
    )

    # R1 cobertura da demanda em cada bloco horario
    for d in DAYS:
        for t in HOURS:
            cover = gp.quicksum(
                x[i, d, s] for i in EMPLOYEES for s in range(NS)
                if SHIFTS[s][1] <= t < SHIFTS[s][2]
            )
            m.addConstr(cover + u[d, t] >= demand(d, t), name=f"R1_{d}_{t}")

    # R2 um turno por dia ou folga
    for i in EMPLOYEES:
        for d in DAYS:
            m.addConstr(gp.quicksum(x[i, d, s] for s in range(NS)) + y[i, d] == 1,
                        name=f"R2_{i}_{d}")

    # R3 carga horaria semanal maxima
    for i in EMPLOYEES:
        m.addConstr(
            gp.quicksum(H_S[s] * x[i, d, s] for d in DAYS for s in range(NS)) <= hmax,
            name=f"R3_{i}")

    # R4 numero minimo de folgas semanais
    for i in EMPLOYEES:
        m.addConstr(gp.quicksum(y[i, d] for d in DAYS) >= fmin, name=f"R4_{i}")

    # R5 interjornada minima de 11h
    for i in EMPLOYEES:
        for d in range(6):
            for (s1, s2) in FORBIDDEN_PAIRS:
                m.addConstr(x[i, d, s1] + x[i, d + 1, s2] <= 1,
                            name=f"R5_{i}_{d}_{s1}_{s2}")

    m.optimize()

    total_demand = sum(demand(d, t) for d in DAYS for t in HOURS)
    res = {
        "label": label,
        "hmax": hmax,
        "fmin": fmin,
        "status": int(m.Status),
        "obj": m.ObjVal,
        "labor_cost": sum(C_S[s] * x[i, d, s].X for i in EMPLOYEES for d in DAYS for s in range(NS)),
        "undercover": sum(u[d, t].X for d in DAYS for t in HOURS),
        "shifts_used": int(round(sum(x[i, d, s].X for i in EMPLOYEES for d in DAYS for s in range(NS)))),
        "hours_paid": sum(H_S[s] * x[i, d, s].X for i in EMPLOYEES for d in DAYS for s in range(NS)),
        "total_demand_personhours": total_demand,
        "runtime": m.Runtime,
        "nodes": int(m.NodeCount),
        "n_vars": m.NumVars,
        "n_bin": m.NumBinVars,
        "n_constrs": m.NumConstrs,
        "mip_gap": m.MIPGap,
        "shift_mix": {SHIFTS[s][0]: int(round(sum(x[i, d, s].X for i in EMPLOYEES for d in DAYS)))
                      for s in range(NS)},
        "employees_active": int(sum(1 for i in EMPLOYEES
                                    if sum(x[i, d, s].X for d in DAYS for s in range(NS)) > 0.5)),
    }
    # cobertura efetiva por bloco (para grafico)
    res["coverage"] = {
        f"{d}": {str(t): int(round(sum(x[i, d, s].X for i in EMPLOYEES for s in range(NS)
                                       if SHIFTS[s][1] <= t < SHIFTS[s][2])))
                 for t in HOURS}
        for d in DAYS
    }
    if save_schedule:
        sched = {}
        for i in EMPLOYEES:
            row = []
            for d in DAYS:
                cell = "FOLGA"
                for s in range(NS):
                    if x[i, d, s].X > 0.5:
                        cell = SHIFTS[s][0]
                row.append(cell)
            sched[i] = row
        res["schedule"] = sched
    return res

# ---------------------------------------------------------------- execucao
scenarios = [
    ("A", 44, 1, "A - Baseline CLT (6x1, 44h)"),
    ("B", 40, 2, "B - Transicao direta (5x2, 40h)"),
    ("D", 36, 3, "D - Radical PEC 8/2025 (4x3, 36h)"),
]

results = {}
print(f"Custo-hora com encargos: R$ {CUSTO_HORA:.2f}")
print(f"Custos por turno: {dict(zip([s[0] for s in SHIFTS], [round(c,2) for c in C_S]))}")
print(f"Pares proibidos (11h): {[(SHIFTS[a][0], SHIFTS[b][0]) for a,b in FORBIDDEN_PAIRS]}")
print()

for key, hmax, fmin, label in scenarios:
    r = build_and_solve(hmax, fmin, label, save_schedule=(key == "A"))
    results[key] = r
    print(f"{label}: obj=R$ {r['obj']:.2f} | subcob={r['undercover']:.0f} "
          f"| turnos={r['shifts_used']} | horas pagas={r['hours_paid']:.0f} "
          f"| t={r['runtime']:.3f}s | nos={r['nodes']}")

# Cenario C: transicao gradual 43/42/41/40 (5x2, F=2)
results["C"] = {"label": "C - Transicao gradual PEC 221/2019", "years": []}
for ano, hm in enumerate([43, 42, 41, 40], start=1):
    r = build_and_solve(hm, 2, f"C_ano{ano}_H{hm}")
    results["C"]["years"].append(r)
    print(f"C ano {ano} (Hmax={hm}h): obj=R$ {r['obj']:.2f} | subcob={r['undercover']:.0f} "
          f"| turnos={r['shifts_used']} | t={r['runtime']:.3f}s")

# demanda agregada para relatorio
results["_meta"] = {
    "custo_hora": CUSTO_HORA,
    "sal_hora": SAL_HORA,
    "piso": PISO_MENSAL,
    "encargos": ENCARGOS,
    "C_S": dict(zip([s[0] for s in SHIFTS], C_S)),
    "demanda_total_semana": sum(demand(d, t) for d in DAYS for t in HOURS),
    "demanda": {str(d): {str(t): demand(d, t) for t in HOURS} for d in DAYS},
    "forbidden_pairs": [(SHIFTS[a][0], SHIFTS[b][0]) for a, b in FORBIDDEN_PAIRS],
}

with open("/home/claude/results.json", "w") as f:
    json.dump(results, f, indent=1)
print("\nResultados salvos em results.json")

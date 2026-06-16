# -*- coding: utf-8 -*-
"""Analises complementares: dimensionamento do quadro, irredutibilidade
salarial e sensibilidade de demanda."""
import json
import math
import gurobipy as gp
from gurobipy import GRB

DAYS = list(range(7))
HOURS = list(range(7, 23))
SHIFTS = [("06-14", 6, 14), ("08-16", 8, 16), ("10-18", 10, 18),
          ("14-22", 14, 22), ("15-23", 15, 23)]
NS = len(SHIFTS)
H_S = [e - s for _, s, e in SHIFTS]
BASE_DEMAND = {7: 3, 8: 4, 9: 5, 10: 6, 11: 7, 12: 8, 13: 7, 14: 6, 15: 5,
               16: 5, 17: 7, 18: 9, 19: 8, 20: 4, 21: 4, 22: 3}
DAY_FACTOR = [1.0, 1.0, 1.0, 1.0, 1.0, 1.3, 0.8]
PISO = 1856.00
ENCARGOS = 0.678
LAMBDA = 1000.0

FORBIDDEN = [(s1, s2) for s1, (_, i1, e1) in enumerate(SHIFTS)
             for s2, (_, i2, e2) in enumerate(SHIFTS) if (24 - e1) + i2 < 11]

def demand(d, t, mult=1.0):
    return math.ceil(BASE_DEMAND[t] * DAY_FACTOR[d] * mult)

def shift_cost(s_idx, divisor):
    _, ini, fim = SHIFTS[s_idx]
    ch = (PISO / divisor) * (1 + ENCARGOS)
    return sum(ch * (1.2 if h >= 22 else 1.0) for h in range(ini, fim))

def solve(n_emp, hmax, fmin, divisor=220, dmult=1.0):
    EMP = list(range(n_emp))
    CS = [shift_cost(s, divisor) for s in range(NS)]
    m = gp.Model()
    m.Params.OutputFlag = 0
    x = m.addVars(EMP, DAYS, range(NS), vtype=GRB.BINARY)
    y = m.addVars(EMP, DAYS, vtype=GRB.BINARY)
    u = m.addVars(DAYS, HOURS, lb=0.0)
    m.setObjective(gp.quicksum(CS[s] * x[i, d, s] for i in EMP for d in DAYS for s in range(NS))
                   + LAMBDA * gp.quicksum(u[d, t] for d in DAYS for t in HOURS), GRB.MINIMIZE)
    for d in DAYS:
        for t in HOURS:
            m.addConstr(gp.quicksum(x[i, d, s] for i in EMP for s in range(NS)
                                    if SHIFTS[s][1] <= t < SHIFTS[s][2]) + u[d, t]
                        >= demand(d, t, dmult))
    for i in EMP:
        for d in DAYS:
            m.addConstr(gp.quicksum(x[i, d, s] for s in range(NS)) + y[i, d] == 1)
        m.addConstr(gp.quicksum(H_S[s] * x[i, d, s] for d in DAYS for s in range(NS)) <= hmax)
        m.addConstr(gp.quicksum(y[i, d] for d in DAYS) >= fmin)
        for d in range(6):
            for (s1, s2) in FORBIDDEN:
                m.addConstr(x[i, d, s1] + x[i, d + 1, s2] <= 1)
    m.optimize()
    return {
        "n_emp": n_emp, "hmax": hmax, "fmin": fmin, "divisor": divisor, "dmult": dmult,
        "obj": m.ObjVal,
        "labor": sum(CS[s] * x[i, d, s].X for i in EMP for d in DAYS for s in range(NS)),
        "under": sum(u[d, t].X for d in DAYS for t in HOURS),
        "shifts": int(round(sum(x[i, d, s].X for i in EMP for d in DAYS for s in range(NS)))),
        "runtime": m.Runtime,
    }

out = {}

# 1) Dimensionamento minimo do quadro no cenario D (36h, F=3)
sizing = []
for n in range(25, 34):
    r = solve(n, 36, 3)
    sizing.append(r)
    print(f"D com {n} func.: under={r['under']:.0f}, labor=R$ {r['labor']:.2f}")
    if r["under"] < 0.5 and len([s for s in sizing if s['under'] < 0.5]) == 1:
        pass
out["sizing_D"] = sizing
n_min_D = next(r["n_emp"] for r in sizing if r["under"] < 0.5)
print(f"Quadro minimo cenario D: {n_min_D}")

# tambem cenario B (por completude) - 25 ja basta?
out["sizing_B"] = [solve(25, 40, 2)]

# 2) Custos sob irredutibilidade salarial (divisor ajustado)
# A: 44h div 220 | B: 40h div 200 | C ano4: 40h div 200 | D: 36h div 180 (quadro minimo)
irr = {
    "A": solve(25, 44, 1, divisor=220),
    "B": solve(25, 40, 2, divisor=200),
    "D": solve(n_min_D, 36, 3, divisor=180),
}
irr["C_anos"] = [solve(25, hm, 2, divisor=dv) for hm, dv in
                 [(43, 215), (42, 210), (41, 205), (40, 200)]]
out["irredutibilidade"] = irr
print("\nIrredutibilidade salarial:")
print(f"  A: R$ {irr['A']['labor']:.2f}")
print(f"  B: R$ {irr['B']['labor']:.2f} (+{100*(irr['B']['labor']/irr['A']['labor']-1):.1f}%)")
for k, r in enumerate(irr["C_anos"], 1):
    print(f"  C ano{k}: R$ {r['labor']:.2f} (+{100*(r['labor']/irr['A']['labor']-1):.1f}%)")
print(f"  D ({n_min_D} func): R$ {irr['D']['labor']:.2f} (+{100*(irr['D']['labor']/irr['A']['labor']-1):.1f}%)")

# 3) Sensibilidade de demanda (+-10%, +20%) nos cenarios A e B e D(quadro min)
sens = {}
for mult in [0.9, 1.0, 1.1, 1.2]:
    sens[str(mult)] = {
        "A": solve(25, 44, 1, dmult=mult),
        "B": solve(25, 40, 2, dmult=mult),
        "D": solve(n_min_D, 36, 3, divisor=180, dmult=mult),
    }
    a, b, dd = sens[str(mult)]["A"], sens[str(mult)]["B"], sens[str(mult)]["D"]
    print(f"\nDemanda x{mult}: A under={a['under']:.0f} labor={a['labor']:.0f} | "
          f"B under={b['under']:.0f} labor={b['labor']:.0f} | "
          f"D under={dd['under']:.0f} labor={dd['labor']:.0f}")
out["sensibilidade"] = sens

with open("/home/claude/results_ext.json", "w") as f:
    json.dump(out, f, indent=1)
print("\nok")

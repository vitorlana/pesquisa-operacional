# -*- coding: utf-8 -*-
import json
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update({"font.size": 10, "figure.dpi": 200, "font.family": "DejaVu Sans"})

with open("/home/claude/results.json") as f:
    R = json.load(f)
with open("/home/claude/results_ext.json") as f:
    E = json.load(f)

HOURS = list(range(7, 23))
BASE = {7: 3, 8: 4, 9: 5, 10: 6, 11: 7, 12: 8, 13: 7, 14: 6, 15: 5, 16: 5,
        17: 7, 18: 9, 19: 8, 20: 4, 21: 4, 22: 3}

# ---- Fig 1: curva de demanda
fig, ax = plt.subplots(figsize=(6.2, 3.2))
dias = [("Dia útil", 1.0, "#1f77b4", "-o"), ("Sábado (×1,3)", 1.3, "#d62728", "-s"),
        ("Domingo (×0,8)", 0.8, "#2ca02c", "-^")]
for nome, f_, c, st in dias:
    ax.plot(HOURS, [math.ceil(BASE[t] * f_) for t in HOURS], st, color=c, label=nome,
            markersize=4, linewidth=1.4)
ax.set_xlabel("Bloco horário (h)")
ax.set_ylabel("Demanda mínima (funcionários)")
ax.set_xticks(HOURS)
ax.grid(alpha=0.3)
ax.legend(frameon=False)
fig.tight_layout()
fig.savefig("/home/claude/fig1_demanda.png", bbox_inches="tight")

# ---- Fig 2: cobertura otima vs demanda (cenario A, dia util e sabado)
cov = R["A"]["coverage"]
fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.0), sharey=True)
for ax, d, titulo, f_ in [(axes[0], "0", "Dia útil (segunda)", 1.0),
                          (axes[1], "5", "Sábado", 1.3)]:
    dem = [math.ceil(BASE[t] * f_) for t in HOURS]
    cb = [cov[d][str(t)] for t in HOURS]
    ax.step(HOURS, dem, where="mid", color="#d62728", linewidth=1.6, label="Demanda $D_{dt}$")
    ax.bar(HOURS, cb, color="#9ecae1", edgecolor="#3182bd", linewidth=0.6,
           label="Cobertura ótima")
    ax.set_title(titulo, fontsize=10)
    ax.set_xlabel("Bloco horário (h)")
    ax.grid(alpha=0.3, axis="y")
axes[0].set_ylabel("Funcionários")
axes[0].legend(frameon=False, fontsize=9)
fig.tight_layout()
fig.savefig("/home/claude/fig2_cobertura.png", bbox_inches="tight")

# ---- Fig 3: custo semanal por cenario, duas hipoteses salariais
lab = ["A\n44h, 6×1", "B\n40h, 5×2", "C (ano 4)\n40h, 5×2", "D\n36h, 4×3"]
horaria = [R["A"]["labor_cost"], R["B"]["labor_cost"], R["C"]["years"][3]["labor_cost"],
           E["sizing_D"][6]["labor"]]  # D com 31 func, custo horario base
irre = [E["irredutibilidade"]["A"]["labor"], E["irredutibilidade"]["B"]["labor"],
        E["irredutibilidade"]["C_anos"][3]["labor"], E["irredutibilidade"]["D"]["labor"]]
xpos = range(4)
fig, ax = plt.subplots(figsize=(6.6, 3.4))
w = 0.38
b1 = ax.bar([x - w/2 for x in xpos], horaria, w, color="#9ecae1", edgecolor="#3182bd",
            label="Remuneração estritamente horária")
b2 = ax.bar([x + w/2 for x in xpos], irre, w, color="#fdae6b", edgecolor="#e6550d",
            label="Irredutibilidade salarial (divisor ajustado)")
base = irre[0]
for bars in (b1, b2):
    for b in bars:
        v = b.get_height()
        pct = 100 * (v / base - 1)
        txt = f"R$ {v:,.0f}".replace(",", ".")
        if abs(pct) > 0.1:
            txt += f"\n({pct:+.1f}%)"
        ax.text(b.get_x() + b.get_width()/2, v + 150, txt, ha="center", fontsize=7.5)
ax.set_xticks(list(xpos))
ax.set_xticklabels(lab, fontsize=9)
ax.set_ylabel("Custo semanal de mão de obra (R$)")
ax.set_ylim(0, max(irre) * 1.22)
ax.grid(alpha=0.3, axis="y")
ax.legend(frameon=False, fontsize=9, loc="upper left")
fig.tight_layout()
fig.savefig("/home/claude/fig3_custos.png", bbox_inches="tight")

# ---- Fig 4: dimensionamento do quadro no cenario D
ns = [r["n_emp"] for r in E["sizing_D"]]
und = [r["under"] for r in E["sizing_D"]]
fig, ax = plt.subplots(figsize=(5.6, 3.0))
ax.plot(ns, und, "-o", color="#d62728", markersize=5)
ax.axvline(31, color="gray", linestyle="--", linewidth=1)
ax.annotate("quadro mínimo viável\n(31 funcionários)", xy=(31, 2), xytext=(31.3, 14),
            fontsize=9, arrowprops=dict(arrowstyle="->", color="gray"))
ax.set_xlabel("Tamanho do quadro |I| (funcionários)")
ax.set_ylabel("Subcobertura total $\\sum u_{dt}$ (pessoas-hora/semana)")
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig("/home/claude/fig4_quadro.png", bbox_inches="tight")
print("figs ok")

# -*- coding: utf-8 -*-
"""
Gera fig6_quadro.png: comparacao do quadro de funcionarios e do custo total
sob turnos flexiveis com jornada fechada (igualdade de horas) e pagamento
horario, para os tres regimes regulatorios A/B/D.

Le o JSON consolidado com granularidade de 15 minutos:
    resultados_flexivel_jornada_fechada_15min.json
"""
import json
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update({
    "font.size": 10,
    "figure.dpi": 200,
    "font.family": "DejaVu Sans",
})

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "resultados_flexivel_jornada_fechada_15min.json")
OUT = os.path.join(HERE, "fig6_quadro.png")

with open(SRC, "r", encoding="utf-8") as f:
    R = json.load(f)

ordem = ["A", "B", "D"]
rotulos = [
    "A\n44 h/sem\n(11×3)",
    "B\n40 h/sem\n(10×4)",
    "D\n36 h/sem\n(9×5)",
]
ativos = [R[k]["funcionarios_ativos"] for k in ordem]
custo = [R[k]["custo_mo"] for k in ordem]
horas = [R[k]["horas_pagas"] for k in ordem]

fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.4))

# ---- Esq.: funcionarios ativos
ax = axes[0]
cores = ["#1f77b4", "#ff7f0e", "#2ca02c"]
bars = ax.bar(rotulos, ativos, color=cores, edgecolor="black", linewidth=0.7)
for b, v in zip(bars, ativos):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.25, f"{v}",
            ha="center", va="bottom", fontsize=11, fontweight="bold")
ax.set_ylabel("Funcionários ativos no ciclo")
ax.set_ylim(0, max(ativos) + 6)
ax.set_title("Quadro mínimo (jornada fechada)", fontsize=10)
ax.grid(alpha=0.3, axis="y")

# anota variacao percentual sobre baseline A
base = ativos[0]
for i, v in enumerate(ativos):
    if i == 0:
        continue
    pct = 100 * (v - base) / base
    ax.text(i, v + 2.2, f"(+{pct:.0f}%)", ha="center", va="bottom",
            fontsize=9, color="#555")

# ---- Dir.: custo total quinzenal
ax = axes[1]
bars = ax.bar(rotulos, custo, color=cores, edgecolor="black", linewidth=0.7)
for b, v in zip(bars, custo):
    ax.text(b.get_x() + b.get_width() / 2, v + 60, f"R$ {v:,.0f}".replace(",", "."),
            ha="center", va="bottom", fontsize=10, fontweight="bold")
ax.set_ylabel("Custo de mão de obra na quinzena (R\\$)")
ax.set_ylim(0, max(custo) * 1.20)
ax.set_title("Custo sob pagamento horário", fontsize=10)
ax.grid(alpha=0.3, axis="y")

base_c = custo[0]
for i, v in enumerate(custo):
    if i == 0:
        continue
    pct = 100 * (v - base_c) / base_c
    sinal = "+" if pct >= 0 else ""
    ax.text(i, v + custo[0] * 0.10, f"({sinal}{pct:.2f}%)",
            ha="center", va="bottom", fontsize=9, color="#555")

fig.suptitle(
    "Turnos flexíveis (15 min) com jornada fechada e pagamento horário",
    fontsize=11, y=1.02,
)
fig.tight_layout()
fig.savefig(OUT, bbox_inches="tight")
print(f"OK -> {OUT}")
print("Resumo:")
for k, lab, a, h, c in zip(ordem, rotulos, ativos, horas, custo):
    print(f"  {k}: {a} ativos, {h:.0f} h pagas, R$ {c:,.2f}")

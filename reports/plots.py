from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
from textwrap import wrap

def _ensure_out(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path

def _wrap_labels(labels, width=10):
    return ["\n".join(wrap(str(x), width=width)) for x in labels]

def plot_top_charts(top_df: pd.DataFrame, out_dir: Path, prefix: str="weekly"):
    """
    Crea tre grafici PNG per i 'Top' selezionati:
      - momentum (bar)
      - drawdown (bar)
      - target weights (bar)
    """
    _ensure_out(out_dir)
    cols_needed = {"Symbol","Momentum","Drawdown","TargetWeight"}
    if not cols_needed.issubset(top_df.columns):
        raise ValueError(f"Mancano colonne in top_df: {cols_needed - set(top_df.columns)}")

    # Ordina per Momentum desc per coerenza visiva
    df = top_df.copy().sort_values("Momentum", ascending=False).reset_index(drop=True)

    # Etichette (wrappate per evitare sovrapposizioni)
    labels = _wrap_labels(df["Symbol"].tolist(), width=12)

    # 1) Momentum
    fig1, ax1 = plt.subplots(figsize=(10, 5))
    ax1.bar(labels, df["Momentum"].values)
    ax1.set_title("Momentum (lookback vs oggi-skip)")
    ax1.set_ylabel("Momentum (ratio - 1)")
    ax1.set_xlabel("Symbol")
    ax1.grid(True, axis="y", alpha=0.3)
    fig1.tight_layout()
    p1 = out_dir / f"{prefix}_top_momentum.png"
    fig1.savefig(p1, dpi=150)
    plt.close(fig1)

    # 2) Drawdown (valori negativi)
    fig2, ax2 = plt.subplots(figsize=(10, 5))
    ax2.bar(labels, df["Drawdown"].values)
    ax2.set_title("Drawdown recente (min)")
    ax2.set_ylabel("Drawdown")
    ax2.set_xlabel("Symbol")
    ax2.grid(True, axis="y", alpha=0.3)
    fig2.tight_layout()
    p2 = out_dir / f"{prefix}_top_drawdown.png"
    fig2.savefig(p2, dpi=150)
    plt.close(fig2)

    # 3) Target Weights
    fig3, ax3 = plt.subplots(figsize=(10, 5))
    ax3.bar(labels, df["TargetWeight"].values)
    ax3.set_title("Pesi target nel portafoglio")
    ax3.set_ylabel("Peso")
    ax3.set_xlabel("Symbol")
    ax3.grid(True, axis="y", alpha=0.3)
    fig3.tight_layout()
    p3 = out_dir / f"{prefix}_top_weights.png"
    fig3.savefig(p3, dpi=150)
    plt.close(fig3)

    return p1, p2, p3

def plot_suggestions_table(sugg_df: pd.DataFrame, out_dir: Path, prefix: str="weekly"):
    """
    Esporta una "tabella" delle suggestion come immagine semplice (testo monospazio).
    """
    _ensure_out(out_dir)
    cols_needed = {"Action","Symbol","Qty","Note"}
    if not cols_needed.issubset(sugg_df.columns):
        raise ValueError(f"Mancano colonne in suggestions: {cols_needed - set(sugg_df.columns)}")

    lines = ["SUGGESTIONS (BUY/SELL/HOLD)", ""]
    for r in sugg_df.itertuples(index=False):
        lines.append(f"{r.Action:>5}  {r.Symbol:<10}  qty={r.Qty:<4}  {r.Note}")
    text = "\n".join(lines) if len(lines) > 2 else "Nessun suggerimento."

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.axis("off")
    ax.text(0.01, 0.99, text, va="top", ha="left", family="monospace")
    fig.tight_layout()
    p = out_dir / f"{prefix}_suggestions.png"
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return p

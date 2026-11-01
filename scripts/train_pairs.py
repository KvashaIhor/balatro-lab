"""Fit the value network on paired outcomes (scripts/rollouts.py): for each decision, how much further the game
went with each option than with the others.

Usage:  python3 -u scripts/train_pairs.py --data runs/value/data/pairs_r0.npz --out runs/value/p1.npz [--epochs 60]
Writes: the .npz the bot loads (balatro.value.ValueNet) and a .json beside it with how well it picks
Log:    logs/value_train.log (append with >>)

Only differences within a decision count: the network's values for a decision's options are centred, and so
are the outcomes, and the loss is the gap between the two. What a seed was going to give anyway cancels out,
and the network learns what each choice changes. A tenth of the decisions is held out: on those it reports the
outcome of its own pick, of the bot's pick and of the best option, each against the decision's average.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from torch import nn  # noqa: E402

from balatro.value import N_FEATURES  # noqa: E402


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def centred(v: torch.Tensor, g: torch.Tensor, n_groups: int) -> torch.Tensor:
    """v minus the mean of its group (g: group index per row, 0..n_groups-1)."""
    sums = torch.zeros(n_groups, device=v.device).index_add_(0, g, v)
    counts = torch.zeros(n_groups, device=v.device).index_add_(0, g, torch.ones_like(v))
    return v - (sums / counts)[g]


def picks(pred: np.ndarray, y: np.ndarray, starts: np.ndarray, ends: np.ndarray, chosen: np.ndarray) -> dict:
    """Outcome of the network's pick, the bot's pick and the best option, each minus the decision's average."""
    net, bot, best, agree = [], [], [], []
    for s, e in zip(starts, ends):
        yy, mean = y[s:e], y[s:e].mean()
        k = int(np.argmax(pred[s:e]))
        net.append(yy[k] - mean)
        best.append(yy.max() - mean)
        if chosen[s:e].any():
            bot.append(yy[int(np.argmax(chosen[s:e]))] - mean)
            agree.append(chosen[s + k] == 1)
    return {"net": float(np.mean(net)), "bot": float(np.mean(bot)), "best": float(np.mean(best)),
            "agree": float(np.mean(agree))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--batch", type=int, default=4096)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--patience", type=int, default=6)
    args = ap.parse_args()
    t0 = time.time()
    d = np.load(args.data)
    x, y, g, chosen = d["X"].astype(np.float32), d["y"].astype(np.float32), d["group"], d["chosen"]
    assert x.shape[1] == N_FEATURES, f"data has {x.shape[1]} features, the bot reads {N_FEATURES}"
    n_groups = int(g.max()) + 1
    starts = np.searchsorted(g, np.arange(n_groups))
    ends = np.append(starts[1:], len(g))
    # Held out by whole games: a game's decisions share its seed (its future cards), so a decision held out
    # while others of its game are trained on would flatter the fit. Older files have no game index, but each
    # game's decisions are saved together in ante order, so a drop in ante starts the next game.
    if "game" in d.files:
        game = d["game"]
    else:
        game = np.cumsum(np.r_[0, np.diff(d["ante"].astype(int)) < 0])
    held = (np.random.default_rng(0).random(int(game.max()) + 1) < 0.1)[game]
    tr_groups, va_groups = np.where(~held)[0], np.where(held)[0]
    rows = lambda groups: np.concatenate([np.arange(starts[k], ends[k]) for k in groups])
    tr_rows, va_rows = rows(tr_groups), rows(va_groups)
    log(f"train pairs: {args.data}: {n_groups} decisions from {int(game.max()) + 1} games, {len(y)} option outcomes; "
        f"{len(va_groups)} decisions held out (whole games)")
    mean, std = x[tr_rows].mean(0), np.maximum(x[tr_rows].std(0), 0.25)
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    xt = torch.from_numpy((x - mean) / std).to(dev)
    yt = torch.from_numpy(y).to(dev)
    model = nn.Sequential(nn.Linear(N_FEATURES, args.hidden), nn.ReLU(), nn.Linear(args.hidden, args.hidden), nn.ReLU(),
                          nn.Linear(args.hidden, 1)).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)

    def batch_of(groups):
        idx = rows(groups)
        local = np.repeat(np.arange(len(groups)), ends[groups] - starts[groups])
        return torch.from_numpy(idx).to(dev), torch.from_numpy(local).to(dev), len(groups)

    def evaluate():
        model.eval()
        with torch.no_grad():
            pred = model(xt)[:, 0].cpu().numpy()
        vi, vl, vn = batch_of(va_groups)
        p, yy = torch.from_numpy(pred).to(dev)[vi], yt[vi]
        mse = float(((centred(p, vl, vn) - centred(yy, vl, vn)) ** 2).mean())
        base = float((centred(yy, vl, vn) ** 2).mean())
        return mse, base, pred

    per_batch = max(1, args.batch // max(1, int(np.mean(ends - starts))))
    best, best_state, stale, fit = float("inf"), None, 0, None
    for epoch in range(1, args.epochs + 1):
        model.train()
        order = np.random.default_rng(epoch).permutation(tr_groups)
        total = 0.0
        for k in range(0, len(order), per_batch):
            bi, bl, bn = batch_of(order[k:k + per_batch])
            loss = ((centred(model(xt[bi])[:, 0], bl, bn) - centred(yt[bi], bl, bn)) ** 2).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += float(loss)
        mse, base, pred = evaluate()
        pk = picks(pred, y, starts[va_groups], ends[va_groups], chosen)
        el = time.time() - t0
        log(f"epoch {epoch}/{args.epochs}: held-out centred mse {mse:.3f} (no-skill {base:.3f}); on held-out decisions, "
            f"vs the decision's average: network's pick {pk['net']:+.3f}, bot's pick {pk['bot']:+.3f}, best {pk['best']:+.3f} "
            f"progress (agrees with the bot {100 * pk['agree']:.0f}%); {el / 60:.1f} min")
        if mse < best - 1e-4:
            best, stale = mse, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            fit = {"mse": mse, "no_skill_mse": base, "epoch": epoch, **{f"pick_{k}": v for k, v in pk.items()}}
        else:
            stale += 1
            if stale >= args.patience:
                log(f"held-out fit stopped improving; keeping epoch {fit['epoch']}")
                break
    model.load_state_dict(best_state)
    weights = {}
    for i, m in enumerate(m for m in model if isinstance(m, nn.Linear)):
        weights[f"W{i}"] = m.weight.detach().cpu().numpy().T.astype(np.float32)
        weights[f"b{i}"] = m.bias.detach().cpu().numpy().astype(np.float32)
    out = Path(args.out)
    np.savez(out, mean=mean.astype(np.float32), std=std.astype(np.float32), **weights)
    out.with_suffix(".json").write_text(json.dumps({"data": args.data, "decisions": n_groups, "outcomes": int(len(y)),
                                                    "seconds": round(time.time() - t0, 1), **fit}, indent=1))
    log(f"wrote {out}: on held-out decisions its pick gains {fit['pick_net']:+.3f} progress over the average option "
        f"(the bot's {fit['pick_bot']:+.3f}, the best {fit['pick_best']:+.3f}); {(time.time() - t0) / 60:.1f} min; exit 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

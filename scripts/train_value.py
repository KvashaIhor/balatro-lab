"""Fit the value network: from a position (balatro.value.features), how far the game went (progress).

Usage:  python3 -u scripts/train_value.py --out runs/value/v1.npz [--rounds 0 1 2] [--epochs 40] [--hidden 256]
Reads:  runs/value/data/round<R>.npz (all rounds when --rounds is left out)
Writes: the .npz the bot loads (balatro.value.ValueNet) and a .json beside it with how well it fits
Log:    logs/value_train.log (append with >>)

A tenth of the games (whole games, so no position of theirs is seen in training) is held out to check the fit;
training stops when that stops improving. Inputs are centred and scaled (rare features at most x4, so a joker
seen in few games can't swamp the rest).
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

DATA = ROOT / "runs" / "value" / "data"


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--rounds", type=int, nargs="*")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--batch", type=int, default=4096)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--patience", type=int, default=4)
    args = ap.parse_args()
    t0 = time.time()
    files = sorted(DATA.glob("round*.npz")) if args.rounds is None else [DATA / f"round{r}.npz" for r in args.rounds]
    xs, ys, gs = [], [], []
    for k, f in enumerate(files):
        d = np.load(f)
        xs.append(d["X"])
        ys.append(d["y"])
        gs.append(d["game"].astype(np.int64) + k * 10_000_000)          # games of different rounds stay apart
    x, y, g = np.concatenate(xs), np.concatenate(ys).astype(np.float32), np.concatenate(gs)
    assert x.shape[1] == N_FEATURES, f"data has {x.shape[1]} features, the bot reads {N_FEATURES}"
    held = np.random.default_rng(0).random(g.max() + 1) < 0.1
    val = held[g]
    log(f"train value: {len(files)} rounds ({', '.join(f.stem for f in files)}), {len(x)} positions from "
        f"{len(np.unique(g))} games; {int(val.sum())} positions held out")
    mean = x[~val].astype(np.float32).mean(0)
    std = np.maximum(x[~val].astype(np.float32).std(0), 0.25)
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")

    def tensor(a):
        return torch.from_numpy(((a.astype(np.float32) - mean) / std).astype(np.float32))
    xt, yt = tensor(x[~val]), torch.from_numpy(y[~val])
    xv, yv = tensor(x[val]).to(dev), torch.from_numpy(y[val]).to(dev)
    model = nn.Sequential(nn.Linear(N_FEATURES, args.hidden), nn.ReLU(), nn.Linear(args.hidden, args.hidden), nn.ReLU(),
                          nn.Linear(args.hidden, 1)).to(dev)
    with torch.no_grad():
        model[-1].bias.fill_(float(y[~val].mean()))
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    base = float(((yv - yt.mean().to(dev)) ** 2).mean())
    best, best_state, stale = float("inf"), None, 0
    n = len(xt)
    for epoch in range(1, args.epochs + 1):
        model.train()
        perm = torch.randperm(n)
        total = 0.0
        for k in range(0, n, args.batch):
            idx = perm[k:k + args.batch]
            xb, yb = xt[idx].to(dev), yt[idx].to(dev)
            loss = ((model(xb)[:, 0] - yb) ** 2).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += float(loss) * len(idx)
        model.eval()
        with torch.no_grad():
            pv = torch.cat([model(xv[k:k + 65536])[:, 0] for k in range(0, len(xv), 65536)])
            mse = float(((pv - yv) ** 2).mean())
            mae = float((pv - yv).abs().mean())
        el = time.time() - t0
        log(f"epoch {epoch}/{args.epochs}: train mse {total / n:.3f}, held-out mse {mse:.3f} (mae {mae:.2f}, "
            f"explains {100 * (1 - mse / base):.1f}% of the spread), {el / 60:.1f} min, about {el / epoch * (args.epochs - epoch) / 60:.1f} min left at most")
        if mse < best - 1e-4:
            best, stale = mse, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            fit = {"mse": mse, "mae": mae, "explained": 1 - mse / base, "epoch": epoch}
        else:
            stale += 1
            if stale >= args.patience:
                log(f"held-out fit stopped improving; keeping epoch {fit['epoch']}")
                break
    linears = [m for m in model if isinstance(m, nn.Linear)]
    model.load_state_dict(best_state)
    weights = {}
    for i, m in enumerate(linears):
        weights[f"W{i}"] = m.weight.detach().cpu().numpy().T.astype(np.float32)
        weights[f"b{i}"] = m.bias.detach().cpu().numpy().astype(np.float32)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, mean=mean, std=std, **weights)
    info = {"rounds": [f.stem for f in files], "positions": int(len(x)), "games": int(len(np.unique(g))),
            "hidden": args.hidden, "seconds": round(time.time() - t0, 1), **fit}
    out.with_suffix(".json").write_text(json.dumps(info, indent=1))
    log(f"wrote {out}: held-out mae {fit['mae']:.2f} progress, explains {100 * fit['explained']:.1f}%; "
        f"{(time.time() - t0) / 60:.1f} min; exit 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

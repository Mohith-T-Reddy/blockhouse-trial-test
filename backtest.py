import pandas as pd
import json
from datetime import timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


class Venue:
    def __init__(self, publisher_id, ask, size, fee=0.0, rebate=0.0):
        self.publisher_id = publisher_id
        self.ask = ask
        self.ask_size = size
        self.fee = fee
        self.rebate = rebate
        self.available_size = size


def load_market_snapshots(path):
    df = pd.read_csv(path, parse_dates=["ts_event"])
    df = df[["ts_event", "publisher_id", "ask_px_00", "ask_sz_00"]].dropna()
    df["ask_px_00"] = pd.to_numeric(df["ask_px_00"], errors="coerce")
    df["ask_sz_00"] = pd.to_numeric(df["ask_sz_00"], errors="coerce").astype(int)
    df = df.dropna()
    df = df.sort_values(["ts_event", "publisher_id"]).drop_duplicates(
        ["ts_event", "publisher_id"]
    )
    snapshots = {}
    for ts, group in df.groupby("ts_event"):
        venues = [
            Venue(r["publisher_id"], r["ask_px_00"], r["ask_sz_00"])
            for _, r in group.iterrows()
        ]
        snapshots[ts] = venues
    return sorted(snapshots.items())


def compute_cost(split, venues, order_size, lambda_over, lambda_under, theta_queue):
    executed, spent = 0, 0
    for i in range(len(venues)):
        fill = min(split[i], venues[i].ask_size)
        executed += fill
        spent += fill * (venues[i].ask + venues[i].fee)
        spent -= max(split[i] - fill, 0) * venues[i].rebate
    under = max(order_size - executed, 0)
    over = max(executed - order_size, 0)
    return (
        spent + lambda_under * under + lambda_over * over + theta_queue * (under + over)
    )


def allocate(order_size, venues, lambda_over, lambda_under, theta_queue):
    step = 100
    splits = [[]]
    for i in range(len(venues)):
        new_splits = []
        for s in splits:
            used = sum(s)
            max_q = min(order_size - used, venues[i].ask_size)
            for q in range(0, max_q + 1, step):
                new_splits.append(s + [q])
        splits = new_splits
    best_cost = float("inf")
    best_split = []
    for alloc in splits:
        if sum(alloc) != order_size:
            continue
        cost = compute_cost(
            alloc, venues, order_size, lambda_over, lambda_under, theta_queue
        )
        if cost < best_cost:
            best_cost = cost
            best_split = alloc
    if not best_split:
        best_split = [0] * len(venues)
    return best_split, best_cost


def run_sor(snapshots, order_size, lambda_over, lambda_under, theta_queue):
    remaining = order_size
    spent = 0
    filled = 0
    history = []

    for ts, venues in snapshots:
        if remaining <= 0:
            break
        active = [v for v in venues if v.ask_size > 0]
        if not active:
            continue
        alloc, _ = allocate(remaining, active, lambda_over, lambda_under, theta_queue)
        for i, shares in enumerate(alloc):
            fill = min(shares, active[i].available_size)
            if fill > 0:
                spent += fill * (active[i].ask + active[i].fee)
                spent -= max(shares - fill, 0) * active[i].rebate
                active[i].available_size -= fill
                remaining -= fill
                filled += fill
        history.append((ts, spent, filled))

    avg_price = spent / filled if filled else 0.0
    return {"cash_spent": spent, "avg_fill_price": avg_price}, history


def best_ask(snapshots, order_size):
    remaining, spent, filled = order_size, 0, 0
    cutoff = snapshots[0][0] + timedelta(minutes=9)
    for ts, venues in snapshots:
        if ts > cutoff or remaining <= 0:
            break
        for v in sorted(venues, key=lambda x: x.ask):
            fill = min(remaining, v.ask_size)
            spent += fill * v.ask
            remaining -= fill
            filled += fill
            if remaining == 0:
                break
    avg_price = spent / filled if filled else 0.0
    return {"cash_spent": spent, "avg_fill_price": avg_price}


def twap(snapshots, order_size):
    start = snapshots[0][0]
    bucket = timedelta(seconds=60)
    shares = order_size // 9
    last = order_size - shares * 8
    spent, filled, idx = 0, 0, 0
    for b in range(9):
        target = shares if b < 8 else last
        used = 0
        while idx < len(snapshots):
            ts, venues = snapshots[idx]
            if ts >= start + (b + 1) * bucket:
                break
            for v in sorted(venues, key=lambda x: x.ask):
                fill = min(target - used, v.ask_size)
                spent += fill * v.ask
                used += fill
                filled += fill
                if used >= target:
                    break
            if used >= target:
                break
            idx += 1
    avg_price = spent / filled if filled else 0.0
    return {"cash_spent": spent, "avg_fill_price": avg_price}


def vwap(snapshots, order_size):
    total_volume, weighted_price = 0, 0
    for _, venues in snapshots:
        for v in venues:
            total_volume += v.ask_size
            weighted_price += v.ask_size * v.ask
    vwap_price = weighted_price / total_volume if total_volume > 0 else float("inf")
    remaining, spent, filled = order_size, 0, 0
    cutoff = snapshots[0][0] + timedelta(minutes=9)
    for ts, venues in snapshots:
        if ts > cutoff or remaining <= 0:
            break
        for v in sorted(venues, key=lambda x: x.ask):
            if v.ask <= vwap_price:
                fill = min(remaining, v.ask_size)
                spent += fill * v.ask
                remaining -= fill
                filled += fill
            if remaining == 0:
                break
    avg_price = spent / filled if filled else 0.0
    return {"cash_spent": spent, "avg_fill_price": avg_price}


def basis_points(p1, p2):
    return ((p1 - p2) / p2) * 10000 if p2 else 0


if __name__ == "__main__":
    order_size = 5000
    snapshots = load_market_snapshots("l1_day.csv")

    lambda_over_list = [0.005, 0.0175, 0.03, 0.0425, 0.05]
    lambda_under_list = [0.05, 0.0875, 0.125, 0.1625, 0.2]
    theta_queue_list = [0.005, 0.0175, 0.03, 0.0425, 0.05]

    best_result = None
    best_params = None
    best_history = []

    for lo in lambda_over_list:
        for lu in lambda_under_list:
            for tq in theta_queue_list:
                result, history = run_sor(snapshots, order_size, lo, lu, tq)
                filled = history[-1][2] if history else 0
                if filled == 0:
                    continue
                best_filled = best_history[-1][2] if best_history else 0
                if (
                    not best_result
                    or result["cash_spent"] < best_result["cash_spent"]
                    or (
                        abs(result["avg_fill_price"] - best_result["avg_fill_price"])
                        < 1e-6
                        and filled > best_filled
                    )
                ):
                    best_result = result
                    best_params = {
                        "lambda_over": lo,
                        "lambda_under": lu,
                        "theta_queue": tq,
                    }
                    best_history = history

    ask = best_ask(snapshots, order_size)
    twap_result = twap(snapshots, order_size)
    vwap_result = vwap(snapshots, order_size)

    timestamps = [ts for ts, _, _ in best_history]
    costs = [cost for _, cost, _ in best_history]
    fills = [filled for _, _, filled in best_history]

    fig, ax1 = plt.subplots(figsize=(12, 6))
    ax1.plot(timestamps, costs, color="blue")
    ax1.set_xlabel("Time")
    ax1.set_ylabel("Cumulative Cost", color="blue")
    ax1.tick_params(axis="y", labelcolor="blue")
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))

    ax2 = ax1.twinx()
    ax2.plot(timestamps, fills, color="green", linestyle="--")
    ax2.set_ylabel("Shares Filled", color="green")
    ax2.tick_params(axis="y", labelcolor="green")

    plt.title("Smart Router: Cumulative Cost and Shares Filled Over Time")
    fig.tight_layout()
    plt.grid(True)
    plt.savefig("results.png")
    plt.close()

    output = {
        "best_parameters": best_params,
        "smart_router": {
            "cash_spent": best_result["cash_spent"],
            "avg_fill_price": best_result["avg_fill_price"],
            "shares_filled": best_history[-1][2] if best_history else 0,
        },
        "best_ask": {
            "cash_spent": ask["cash_spent"],
            "avg_fill_price": ask["avg_fill_price"],
            "shares_filled": order_size,
        },
        "twap": {
            "cash_spent": twap_result["cash_spent"],
            "avg_fill_price": twap_result["avg_fill_price"],
            "shares_filled": order_size,
        },
        "vwap": {
            "cash_spent": vwap_result["cash_spent"],
            "avg_fill_price": vwap_result["avg_fill_price"],
            "shares_filled": order_size,
        },
        "savings_vs_best_ask_bp": basis_points(
            ask["avg_fill_price"], best_result["avg_fill_price"]
        ),
        "savings_vs_twap_bp": basis_points(
            twap_result["avg_fill_price"], best_result["avg_fill_price"]
        ),
        "savings_vs_vwap_bp": basis_points(
            vwap_result["avg_fill_price"], best_result["avg_fill_price"]
        ),
    }

    print(json.dumps(output, indent=2))

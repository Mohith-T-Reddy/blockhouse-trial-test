# Github Link

https://github.com/Mohith-T-Reddy/blockhouse-trial-test.git

# Smart Order Routing Backtest

This project simulates a Smart Order Router based on the static cost model from Cont & Kukanov. It splits a 5,000-share buy order across multiple venues using snapshot market data, and tries to find the cheapest way to execute the full order.

The model includes penalties for overfilling, underfilling, and queue position, and uses those to guide how the order gets split at each point in time.

## What's implemented

- The allocator follows the exact logic from the pseudocode, using 100-share steps.
- Market data is processed snapshot by snapshot, ordered by `ts_event`.
- At each step, the router tries all valid ways to allocate the remaining shares across venues.
- A small grid search is used to find the best values for `lambda_over`, `lambda_under`, and `theta_queue`.

## Baseline comparisons

The tuned router is tested against three simpler strategies:

- **Best Ask** - takes as much as possible from the venue with the lowest ask
- **TWAP** - splits the order evenly across nine one-minute intervals
- **VWAP** - only fills when the price is at or below the volume-weighted average (weighted by displayed size)

## Output

At the end, the script prints one JSON object with:

- The best parameters found
- Total cash spent and average fill price for the router
- The same for each baseline
- Savings in basis points compared to each

A plot of cumulative cost over time is saved as `results.png`.

## Improvement idea

Right now, the model assumes any order at the front of the book always gets filled. In reality, orders might miss fills due to queueing effects. A more realistic model would simulate the chance of not getting filled even when prices match, depending on how deep you are in the queue.

## Requirements

- Python 3.8+
- numpy
- pandas
- matplotlib

## Logic flow

```mermaid
graph TD
    A[Start] --> B[Read market snapshot CSV]
    B --> C[Preprocess: group by timestamp and venue, <br> keeping only the first quote per publisher_id]
    C --> D[Set up a grid of parameter values: <br> - overfill_penalty <br> - underfill_penalty <br> - queue_penalty]
    D --> E[For each combination of parameters:]
    E --> F[Run smart router: <br> - At each timestamp: <br>   - Allocate shares using static cost model <br>   - Fill as much as possible from each venue <br>   - Carry unfilled shares to next step <br> - Track total cost and fills]
    F --> G["Store best result seen so far <br> (lowest cost, highest fill)"]
    G --> H[After search, take best parameter set found]
    H --> I[Run baseline strategies for comparison: <br> - Best Ask: take from cheapest venue <br> - TWAP: spread evenly over 9 mins <br> - VWAP: fill when ask ≤ avg price]
    I --> J[Compare router vs. baselines: <br> - Cash spent <br> - Fill price <br> - Savings in basis points]
    J --> K[Generate output: <br> - Print JSON summary <br> - Save cumulative cost chart as PNG]
    K --> L[Done]

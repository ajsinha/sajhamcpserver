# Tutorial 12: Analyse a Tool's Result in the Python Playground

Call a SAJHA tool from Python running in your browser, turn its result into a pandas
DataFrame, and chart it with matplotlib, without installing anything. The playground is
described in the [Python Playground](../getting-started/Python%20Playground.md) guide.

## What you'll learn

- How to run Python cells in the playground, and what the outputs look like
- How `sajha.call()` runs a server tool with your permissions and returns Python data
- How to reshape a tool's result with pandas and plot it
- How to stop a runaway cell, and how to keep your work

## Prerequisites

- A running server you can sign in to ([Tutorial 1](TUTORIAL_01_getting_started.md))
- The Python runtime available to the playground: either the administrator has run
  `python scripts/fetch_pyodide.py`, or `playground.assets` is `cdn`. If neither is true
  the page tells you so.

The tool used here, `calc_loan_amortization`, is one of the offline financial calculators,
so it needs no API key or network access from the server.

## Steps

### 1. Open the playground

Sign in and choose **Tools → Python Playground** (or **Python Playground** in the
dashboard's quick actions). The page opens at `/playground`. The status pill at the top
right shows the runtime loading, then **Python 3.x ready**.

If the notebook already has cells (an earlier draft), use **Add cell** for a fresh one, or
pick an example from **Examples** to replace them.

### 2. Run a first cell

Type this into a cell and press **Ctrl+Enter** (**Cmd+Enter** on a Mac):

```python
import sajha
mine = [t["name"] for t in sajha.tools()]
print(len(mine), "tools available to me")
"calc_loan_amortization" in mine
```

`sajha.tools()` asks the server which tools you may run. The printed line appears as
plain output and the last expression, `True`, is shown below it as a REPL would show it.

### 3. Call the tool

In a new cell:

```python
loan = sajha.call("calc_loan_amortization", principal=300000, annual_rate=6, months=360)
{k: v for k, v in loan.items() if k != "yearly_schedule"}
```

The call is an ordinary `POST /api/tools/execute` with your session, logged and authorized
as on the Tools page. The result is plain Python data: the monthly payment, the totals,
and a `yearly_schedule` list with one row per loan year.

### 4. Make a DataFrame

```python
import pandas as pd

schedule = pd.DataFrame(loan["yearly_schedule"]).set_index("year")
schedule["share of payment to interest"] = (
    schedule.interest / (schedule.interest + schedule.principal)).round(3)
schedule.head(10)
```

The first time a cell imports pandas, the **Packages** line fills in as numpy, pandas and
their dependencies load. The DataFrame shows as a table.

### 5. Chart it

```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(8, 3.5))
ax.bar(schedule.index, schedule.principal, label="principal")
ax.bar(schedule.index, schedule.interest, bottom=schedule.principal, label="interest")
ax.set_xlabel("loan year"); ax.set_ylabel("paid that year")
ax.set_title("Where a 6% 30-year payment goes")
ax.legend()
plt.show()
```

The figure appears below the cell as an image. Early years are mostly interest; the
crossover year is `schedule[schedule.principal > schedule.interest].index.min()`.

### 6. Compare scenarios

Each call is cheap, so call the tool in a loop and compare:

```python
rows = []
for rate in (4, 5, 6, 7):
    for months in (180, 360):
        r = sajha.call("calc_loan_amortization", principal=300000, annual_rate=rate, months=months)
        rows.append({"rate %": rate, "years": months // 12,
                     "monthly": r["monthly_payment"], "total interest": r["total_interest"]})
compare = pd.DataFrame(rows)
compare.pivot(index="rate %", columns="years", values="total interest")
```

### 7. Stop a runaway cell

Run a cell that never ends:

```python
n = 0
while True:
    n += 1
```

Press **Stop**. The cell ends with `KeyboardInterrupt`, and `n` is still defined: run
`n` in another cell to see how far it got. **Reset** is the bigger hammer: it restarts
Python and clears every variable.

### 8. Keep your work

- **Save** keeps the notebook in this browser; **Load** brings it back. The page also
  keeps a draft and restores it when you come back.
- **.py** downloads all cells as one file with `# %%` cell markers; **Open** reads such a
  file, or the code cells of a Jupyter `.ipynb`.

## What you built

A notebook that fetches data from a SAJHA tool, analyses it with pandas and charts it, all
in the browser. Nothing ran on the server except the tool itself, under your permissions.

## What next

- The **Examples** menu has SciPy, scikit-learn and Ask SAJHA (`sajha.ask()`) notebooks.
- Building a tool in MCP Studio's Python code creator? **Open in playground** sends the
  function here, with a cell that calls it.
- Headers, asset options and limits: [Python Playground](../getting-started/Python%20Playground.md).
- Next tutorial: [Run SAJHA on Several Workers](TUTORIAL_13_run_sajha_on_several_workers.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.

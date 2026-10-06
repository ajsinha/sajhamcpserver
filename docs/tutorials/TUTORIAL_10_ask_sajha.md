# Tutorial 10: Ask SAJHA

Ask a question in the web console and read the answer the way SAJHA built it: the tools it
considered, the calls it made, what each returned, and how confident the answer is. The
page and the endpoint behind it are described in the
[Intelligence Layer](../architecture/Intelligence%20Layer.md#using-ask-sajha) guide.

## What you'll learn

- How to ask a question and follow the tool chain behind the answer
- What the confidence score and the sources mean
- What the mock model can answer, and how to switch to a real one
- How to get the same answer from code with `POST /api/ai/ask`

## Prerequisites

- A running server you can sign in to ([Tutorial 1](TUTORIAL_01_getting_started.md))
- Nothing else: out of the box the built-in mock model answers, with no API key

## Steps

### 1. Open the page

Sign in and choose **AI → Ask SAJHA** in the top menu (or **Ask SAJHA** in the dashboard's
quick actions). The page opens at `/ask`: the conversation on the left, and on the right
the *sky*, where every star is a tool this server has loaded, grouped by provider.

If a **Mock model active** pill shows next to the model picker, no real LLM provider is
enabled and the mock planner is answering. That is enough for this tutorial.

### 2. Ask an example question

Click the example chip **What is the percentage change from 80 to 100?** (or type it and press
Enter). Watch both halves of the page:

1. **Considered N tools.** SAJHA's tool search shortlists the tools that match the question,
   and only the ones you are allowed to run. Their stars light up.
2. **A tool call.** The model calls `calc_percentage_change` with `old_value: 80` and
   `new_value: 100`. A line runs to that tool's star, and a chip appears in the answer.
3. **The result.** The chip shows the tool's result and how long it took; the star shows the
   same summary in green (red would mean the call failed).
4. **The answer** streams in, followed by its **confidence**.

Open the `calc_percentage_change` chip to see the exact arguments sent and the result returned.

### 3. Read the confidence and the sources

The confidence badge is not the model's opinion of itself. It is computed from the tool
results the answer rests on, using the composition framework: a calculator is deterministic
(1.0), a market-data API somewhat less, a failed call lowers the score, and an answer resting
on no tool result scores 0.5. **Sources** lists the tool calls the answer cites, numbered as
on the chips.

### 4. Try a question that uses two tools

Click **Compare the Sharpe ratio and Sortino ratio for a return of 12 with risk free rate 4
and volatility 15**. The chain now has two links, `calc_sharpe_ratio` and
`calc_sortino_ratio`, and the answer cites both.

### 5. Know what the mock can do

The mock planner picks tools by keywords and fills arguments from the numbers in the
question, so it handles calculator questions phrased with parameter names ("face value
1000, coupon rate 5, yield 4.5 over 10 years"). It does not understand language. For real
questions, enable a provider: set `SAJHA_AI_OPENAI_ENABLED=true` and `OPENAI_API_KEY`, point
the default alias at it with `SAJHA_AI_ALIASES_DEFAULT="openai,mock/mock-planner"`, and restart
(the [Intelligence Layer](../architecture/Intelligence%20Layer.md#4-configuration) guide lists
every provider). The pill disappears, and the model picker lists the aliases.

### 6. Stop, confirm, start again

- **Stop** (or Escape) abandons a question while it is running.
- A tool marked destructive is never run without you: the answer shows a card naming the
  call and its arguments, with **Confirm and run** and **Cancel**.
- Each question is answered on its own; SAJHA does not see your earlier questions. The
  conversation stays in this browser tab until you click **New chat** or close the tab.

### 7. Ask from code

The page is a client of `POST /api/ai/ask`. With an API key:

```bash
curl -s http://localhost:3002/api/ai/ask \
  -H "X-API-Key: sja_your_key" -H "Content-Type: application/json" \
  -d '{"question": "What is the percentage change from 80 to 100?"}'
```

The JSON result has `answer`, `confidence`, `steps`, `citations` and `caveats`. Add
`-H "Accept: text/event-stream"` to receive the same step events the page animates.

## What next

- [Intelligence Layer](../architecture/Intelligence%20Layer.md): providers, the gateway, the ask loop and its event stream
- [Composition Framework](../architecture/Composition%20Framework.md): where the confidence score comes from
- [API Reference](../protocol/API%20Reference.md): every endpoint

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.

# Agent Analysis

## 1. Workflow vs. agent

The model makes the research decisions: it chooses search queries, selects URLs from search results, decides what facts might represent a development, assigns a relevance score, and decides when it has enough evidence to call `finish`. My code controls the parts that need to be predictable. It loads the policy, exposes only the configured tools, validates URLs, enforces every budget, skips previously fetched URLs, verifies evidence, merges developments, calculates the Top K, saves state, and classifies failures.

One decision I moved out of the model was whether it could continue searching without fetching evidence. In `runtime.py`, another search is blocked when `searches >= fetches + 2`. The model receives a message telling it to fetch a result before searching again. I made that deterministic because the early trace showed the model repeatedly generating slightly different searches instead of reading an article. Search pacing affects both the budget and whether the final report has evidence, so it should not depend entirely on the model following a suggestion.

## 2. The network

Run 1 contains 36 trace events: 18 model calls and 18 tool calls. Only 22 of those events made external network round trips: 18 calls to Groq, three advanced searches to Tavily, and one article request to Coachella. The remaining tool work was local: `finish` was a Python function and 13 attempted searches were blocked by the runtime after the search-without-fetch limit was reached. The run used 40,556 model tokens.

The trace covers about 199.7 seconds of elapsed time. Summed call latency was about 200.5 seconds. Groq used 188.8 seconds, or roughly 94% of the measured time. Tavily searches used 11.6 seconds, or about 5.8%, and the Coachella fetch used about 0.12 seconds. The model calls therefore dominated the runtime, especially as the conversation and tool-result context grew. The authenticated localhost calls used to load and save MongoDB-backed state were outside this trace, so I did not include them in the 22 external round trips.

## 3. “New”

Each development receives a deterministic key made from its normalized `organization`, `technology`, and `action` fields. Normalization lowercases the combined string and replaces punctuation and spaces with hyphens. If a candidate has the same key as a saved development, the code treats it as the same development and adds any new source URLs. The current Top K is compared with the saved `last_top_k`: unseen keys are New, repeated keys are Still tracking, and previous Top-K keys that disappear are Dropped.

This method can incorrectly merge unrelated articles when their structured fields are vague. That happened in these runs. The fallback for both the Puerto Rico TechCrunch article and the findme App Store article used `Needs review` for organization and technology and `Fetched article` for action. Those unrelated articles therefore received the same key. The later report displayed findme as Still tracking while retaining the Puerto Rico source. I would fix this by refusing generic fallback fields or by including a normalized title/entity fingerprint when the structured fields are incomplete.

## 4. Failure

For HTTP tools, a short-window 429 is classified as transient:

```python
if response.status_code == 429 or response.status_code >= 500:
    raise TransientServiceError(...)
```

`with_retries` catches that error and applies capped exponential backoff:

```python
time.sleep(min(2 ** attempt, 8))
```

With `max_retries: 3`, an HTTP operation gets the original attempt plus at most three retries. Model calls use three total attempts with one- and two-second waits. If the retries are exhausted, the tracker stops and writes a partial report using the evidence already fetched.

A per-minute limit is temporary, so it is retried. A daily cap is terminal: `daily quota`, `daily limit`, `quota exceeded`, and `insufficient_quota` are terminal markers, so the run stops immediately instead of wasting requests that cannot succeed that day. An intermediate October 6 run exposed an earlier classification bug: Groq returned a tokens-per-minute 429, but the text also contained a billing upgrade link, so the old code marked it terminal. I removed the generic billing-link match. The current code now retries that per-minute error while keeping actual authentication, payment-required, unavailable-model, and daily-cap failures terminal.

## 5. Budget

Measured from run 1, one run used 18 Groq requests and 40,556 total model tokens. It made three Tavily advanced searches. Advanced search costs two Tavily credits, so the search portion cost six credits. The direct article fetch used ordinary HTTP and did not consume a Tavily search credit.

Groq's current free limit for `openai/gpt-oss-120b` is 1,000 requests and 200,000 tokens per day, with an 8,000-token-per-minute limit. Tavily's current Researcher plan provides 1,000 credits per month. At one run per day, neither free tier runs out: 40,556 Groq tokens is below the daily cap, which resets each day, and approximately 30 daily runs would use about 180 Tavily credits in a month. If I ran several times in one day, Groq would be the first practical limit because a fifth run at the measured token usage would exceed 200,000 daily tokens. If Tavily credits did not reset monthly, six credits per run would exhaust 1,000 credits on approximately run 167.

Rate-limit references:

- Groq: https://console.groq.com/docs/rate-limits
- Tavily: https://docs.tavily.com/documentation/api-credits

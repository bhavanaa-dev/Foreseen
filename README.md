# FORESEEN

### See beyond the price.

**FORESEEN is an evidence-driven product research tool that helps people make more informed used-product buying decisions.**

A price on its own tells only part of the story. FORESEEN examines available market listings, checks whether products match the requested specifications, compares observed prices, and communicates how reliable the available evidence is.

Instead of blindly recommending the cheapest listing or presenting a single number as the truth, FORESEEN makes the evidence behind a price easier to understand.

---

## Why FORESEEN?

Buying a used product can be confusing. Similar product names may refer to different models, configurations, or conditions. Listings can also vary significantly in price, and repeated listings can distort a comparison.

FORESEEN addresses these problems through:

- **Specification-aware matching** — distinguishes relevant listings from ambiguous or mismatched products.
- **Evidence-based price analysis** — calculates price summaries from eligible listings rather than inventing estimates.
- **Transparent confidence** — communicates when the available evidence is limited.
- **Availability Lens** — compares eligible listings appearing early in search results with the broader eligible set returned by the same search.
- **Traceable evidence** — presents the listings behind the analysis so users can inspect the source information.
- **Honest uncertainty** — reports insufficient evidence instead of substituting prices from a different product.

## How it works

1. **Search:** Enter a product and its relevant specifications.
2. **Collect:** FORESEEN uses available Google Shopping data through SerpApi or reads eligible cached results when applicable.
3. **Match:** Listings are classified according to how closely their titles and available details match the requested product.
4. **Analyze:** Eligible prices are summarized using statistics such as the median, minimum, maximum, quartiles, and spread when sufficient evidence is available.
5. **Understand:** Review the Availability Lens, confidence information, and source listings before making a buying decision.

## Key features

### 1. Specification-aware product matching

A similar product is not necessarily the same product. FORESEEN separates matching, ambiguous, and mismatched listings to reduce misleading comparisons.

### 2. Price statistics with context

Where eligible price observations are available, FORESEEN can present:

| Metric | What it tells you |
|---|---|
| Median | The middle observed price |
| Minimum | The lowest eligible observed price |
| Maximum | The highest eligible observed price |
| Q1 and Q3 | The lower and upper quartiles |
| Price spread | The difference between the maximum and minimum |
| Confidence | How cautiously the estimate should be interpreted |

These are summaries of the collected evidence, not guarantees of a product's fair value.

### 3. Availability Lens

Search ranking affects which listings people notice first. The Availability Lens contrasts eligible priced listings among the first-page results with the broader eligible set returned by the same search.

It helps users understand how the visible selection may differ from the wider set of observed listings.

The two groups can overlap, and Google Shopping results are not a complete representation of the market. The comparison should therefore be treated as context, not as proof of market-wide pricing.

### 4. Transparent evidence

FORESEEN is designed to make its conclusions inspectable. Users can review available listing information and understand why a result may be preliminary or why a product search might not have enough matching evidence.

### 5. Graceful handling of missing evidence

When a search produces too few eligible listings, FORESEEN communicates the limitation rather than manufacturing a confident-looking estimate.

---

## Technology stack

- **Language:** Python
- **Web framework:** Flask
- **Market data:** Google Shopping results through SerpApi
- **Analysis:** Python-based product matching and price statistics
- **Frontend:** HTML, CSS, and Jinja templates
- **Testing:** Python `unittest`
- **Deployment:** Suitable for a Python-compatible hosting platform such as Render

---

## Getting started

### Prerequisites

- Python 3
- pip
- A SerpApi API key for live market lookups
- Git, if cloning the repository

### 1. Clone the repository

Replace `YOUR_USERNAME` with your GitHub username.

```bash
git clone https://github.com/YOUR_USERNAME/foreseen.git
cd foreseen
```

### 2. Create a virtual environment

**Windows PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell prevents environment activation, you can continue using `py -m pip` without activating it.

### 3. Install dependencies

```powershell
py -m pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root and add:

```dotenv
SERPAPI_API_KEY=your_serpapi_api_key
```

Replace the placeholder with your own key.

**Security:** Never commit `.env` or expose your API key in source code, screenshots, logs, or public issues. Keep `.env` listed in `.gitignore`. A `.env.example` file can document the required variable without containing a real secret.

### 5. Start the application

From the repository root:

```powershell
py backend/app.py
```

Open the local address printed by Flask, typically:

`http://127.0.0.1:8000`

Keep the terminal running while using the application. Stop the server with `Ctrl+C`.

---

## Running tests

Run the project's test suite from the repository root:

```powershell
py -m unittest discover -s tests
```

The tests cover application routes and aspects of product matching, price estimation, and evidence rendering.

Run the tests after changing application code or templates. Treat the current test output as the source of truth for the status of the suite.

---

## Market data and limitations

FORESEEN's conclusions depend on the quality and coverage of the listings available to it.

- Search results may be incomplete, stale, duplicated, or unavailable.
- Product titles may not establish every specification or condition.
- A low price does not necessarily mean a good deal.
- Refurbished, renewed, open-box, and used products may not be directly comparable.
- A small sample can produce a wide or unrepresentative price range.
- Cached results may not reflect current availability or current prices.
- Google Shopping results represent the listings returned for a search, not the entire market.
- API access, quotas, connectivity, and provider responses can affect live lookups.

FORESEEN is a research aid, not a guarantee of fair value, listing authenticity, product condition, or seller reliability. Verify the listing and seller details independently before purchasing.

---

## Deployment

FORESEEN can be deployed to a Python-compatible hosting provider.

For a Render deployment, configure the repository as a Python web service, install dependencies with:

```bash
pip install -r requirements.txt
```

If `gunicorn` is included in `requirements.txt` and the package imports work in the deployment environment, use:

```bash
gunicorn backend.app:app
```

Configure `SERPAPI_API_KEY` through the hosting provider's environment-variable settings rather than committing it to GitHub.

Before deployment, verify that the application can import `backend.app`, that the required cached files are included if the demo depends on them, and that the service starts successfully. Follow the provider's logs if the startup command needs adjustment.

---

## Project structure

```text
FORESEEN/
├── backend/
│   ├── app.py
│   ├── main.py
│   ├── price_estimator.py
│   └── shopping.py
├── cache/
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

The exact contents may evolve as the project develops. Keep API credentials and local-only files out of version control.

---

## Project philosophy

> A price means little until you know what it was measured against.

FORESEEN prioritizes evidence over false precision. Its goal is not simply to display a number, but to help users understand what that number represents, which listings support it, and where uncertainty remains.

### Built for more informed buying decisions.

**FORESEEN — See beyond the price.**

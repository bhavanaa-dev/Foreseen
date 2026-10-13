# FORESEEN — See Beyond the Price

**An evidence-driven tool for analyzing used-product prices using real market data.**

[Live Demo](https://foreseen-nine.vercel.app/) · [GitHub Repository](https://github.com/bhavanaa-dev/Foreseen) · [Demo Video](https://drive.google.com/file/d/1X3P8nMjfIZfhq2EbplhilrcSgGrDibzq/view?usp=sharing)

## Overview

Buying a used product can be difficult when there is no clear way to determine whether the asking price is reasonable. Prices vary across listings depending on product specifications, condition, availability, and sellers. Comparing a few listings manually does not always provide a reliable picture of the market.

**FORESEEN** was built to help address this problem. It analyzes available shopping listings and presents price-related insights to help users make more informed decisions when purchasing used products.

The application retrieves Google Shopping results through SerpApi, processes the returned listing data, matches relevant product specifications, and calculates market statistics. It also presents confidence indicators to communicate how much supporting evidence is available for an analysis.

Rather than treating a single price as the definitive value of a product, FORESEEN focuses on the evidence behind the estimate.

## Motivation

The idea originated from my own experience buying a laptop. I found it difficult to compare the available options and determine whether I was paying a fair price. After the purchase, I felt that I might have overpaid.

This made me think about how many buyers face the same uncertainty, particularly in the second-hand market, where prices can vary significantly and reliable comparisons are not always easy to make.

I wanted to build a tool that could turn available market data into understandable insights and help buyers evaluate prices with more confidence.

That idea became FORESEEN.

## Key Features

### 1. Market Data Retrieval

FORESEEN integrates SerpApi to retrieve Google Shopping results for a user's product query. These results provide the listing data used in the subsequent analysis.

### 2. Product Specification Matching

Not every search result represents the same product. Differences in models, configurations, and specifications can make direct price comparisons misleading.

FORESEEN processes the available listing information to identify relevant matches and improve the quality of comparisons.

### 3. Price Analysis and Statistics

The application analyzes prices from the available relevant listings and presents market statistics to help users understand price ranges and variation.

These statistics provide context for evaluating an asking price rather than relying on a single listing.

### 4. Confidence Indicators

Price analysis is only as useful as the evidence supporting it. FORESEEN includes confidence indicators intended to communicate the strength of the available evidence.

The amount and relevance of the available data matter: a limited set of comparable listings should not be interpreted in the same way as a stronger set of matching results.

### 5. Availability Lens

The Availability Lens provides another way to explore the available listings. It helps users compare first-page results with broader search results and understand how listing availability and prices can vary.

This is useful because the first few search results may not represent the wider market.

### 6. Evidence-Based Results

FORESEEN aims to avoid presenting unsupported estimates as certain answers. Its analysis depends on the available shopping data and the relevance of the matching listings.

The goal is to provide useful context while making the limitations of the available evidence clear.

## How It Works

The application follows a data-processing workflow:

1. **Product query:** The user enters the product they want to analyze.
2. **Data retrieval:** FORESEEN uses SerpApi to retrieve relevant Google Shopping results.
3. **Listing processing:** The returned data is processed to extract useful product and pricing information.
4. **Specification matching:** Listings are evaluated for relevance to the requested product.
5. **Statistical analysis:** Prices from relevant listings are analyzed to calculate market statistics and identify variation.
6. **Result presentation:** The application displays the analysis, supporting information, and confidence indicators through its interface.

The quality of the output depends on the availability and relevance of the retrieved data.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Backend logic and data processing |
| Flask | Web application and request handling |
| SerpApi | Retrieving Google Shopping search results |
| HTML | Structuring the web interface |
| CSS | Styling and layout |
| JavaScript | Client-side interactions |
| Vercel | Application deployment |

## Architecture

FORESEEN separates the user-facing interface from the server-side analysis workflow.

```text
User
  |
  v
Web Interface
  |
  v
Flask Backend
  |
  v
SerpApi
  |
  v
Google Shopping Results
  |
  v
Listing Processing
  |
  v
Specification Matching
  |
  v
Price Statistics and Confidence Indicators
  |
  v
Analysis Results
```

SerpApi provides the external shopping data, while the backend processes the available results and prepares the information displayed to the user.

## Running Locally

### Prerequisites

- Python 3.10 or a compatible version supported by the project dependencies
- pip
- A SerpApi API key

### 1. Clone the repository

```bash
git clone https://github.com/bhavanaa-dev/Foreseen.git
cd Foreseen
```

### 2. Create a virtual environment

**Windows (PowerShell):**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can run the project's Python commands using `.venv\Scripts\python.exe` directly.

### 3. Install dependencies

```bash
py -m pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root and add your SerpApi key:

```env
SERPAPI_API_KEY=your_serpapi_api_key
```

Replace the placeholder with your own API key.

**Security note:** Never commit your `.env` file, publish your API key, or expose secret credentials in client-side code. Configure the same environment variable in your deployment settings.

### 5. Start the application

Use the entry point configured in the repository. If the application supports running the backend module directly, use:

```powershell
py backend/app.py
```

Otherwise, use the appropriate Flask entry point documented by the project.

Open the local address printed by the application in your browser.

## Deployment

FORESEEN is deployed on Vercel.

- **Live application:** https://foreseen-nine.vercel.app/
- **Source code:** https://github.com/bhavanaa-dev/Foreseen

The deployed application requires its environment variables to be configured securely. API-dependent features also depend on the availability of the external data service.

## Responsible Use and Limitations

FORESEEN is intended to support buying decisions, not to guarantee the exact value of a product.

- Search results may contain irrelevant, incomplete, or outdated listings.
- Products with similar names may differ in specifications or condition.
- Prices can vary by seller, location, availability, and other factors.
- Statistical summaries are only as representative as the matching listings used to calculate them.
- Confidence indicators should be interpreted in the context of the available evidence.
- Google Shopping results do not necessarily represent every listing in the second-hand market.

Users should review the underlying product details and consider the condition of the item before making a purchase.

## Future Improvements

Potential areas for further development include:

- More accurate matching of product models and configurations.
- Improved handling of product condition and used-versus-new listings.
- Broader coverage across product categories and marketplaces.
- Historical price tracking and price trend analysis.
- More detailed explanations of the evidence behind each estimate.
- Further improvements to data quality and confidence calibration.

## What I Learned

Building FORESEEN gave me practical experience with backend development, external API integration, data processing, product matching, statistical analysis, debugging, and deployment.

It also taught me the importance of considering data quality when building applications that make recommendations. Producing a number is relatively straightforward; producing a number that users can interpret in the right context is much more challenging.

FORESEEN began with a problem I experienced personally. Building it helped me explore how software and real market data can work together to make everyday purchasing decisions more informed.

## Acknowledgements

- [SerpApi](https://serpapi.com/) for providing access to Google Shopping search results.
- The open-source tools and libraries used throughout development.

## Author

**Bhavana S**

GitHub: [@bhavanaa-dev](https://github.com/bhavanaa-dev)

---

**FORESEEN — See beyond the price.**

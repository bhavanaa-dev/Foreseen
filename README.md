# FORESEEN — See Beyond the Price

**An evidence-driven tool for making smarter used-product buying decisions.**

🌐 **Live Demo:** [https://foreseen-nine.vercel.app/](https://foreseen-nine.vercel.app/)

FORESEEN helps users evaluate used-product prices using market listings, specification matching, statistical analysis, and transparent confidence indicators. Instead of relying on a single listing or an arbitrary estimate, it helps users understand the available market evidence before making a purchase.

## ✨ Features

- **Market Price Analysis** — Analyze used-product prices using real marketplace search results.
- **Specification Matching** — Compare listings based on relevant product specifications to improve price comparisons.
- **Price Statistics** — Understand market price ranges, averages, and variation.
- **Confidence Indicators** — See how much supporting evidence is available for an estimate.
- **Availability Lens** — Explore listing availability and compare the first-page results with the broader market.
- **Evidence-Based Results** — Avoid misleading estimates when relevant market data is insufficient.
- **Clean User Interface** — A simple, modern interface designed to make buying decisions easier.

## 🛠️ Tech Stack

- **Backend:** Python, Flask
- **Market Data:** SerpApi Google Shopping
- **Frontend:** HTML, CSS, JavaScript, Jinja templates
- **Deployment:** Vercel

## ⚙️ How It Works

1. Enter the product you want to evaluate.
2. FORESEEN retrieves relevant shopping listings.
3. The system compares product specifications and filters relevant evidence.
4. Price statistics and confidence indicators are calculated from the available data.
5. Review the results and use the market evidence to make a more informed buying decision.

## 🚀 Getting Started

### Prerequisites

- Python 3.10 or later
- A SerpApi API key

### Installation

Clone the repository:

```bash
git clone https://github.com/bhavanaa-dev/Foreseen.git
cd Foreseen
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file in the project root and add your SerpApi key:

```env
SERPAPI_API_KEY=your_serpapi_api_key
```

Replace `your_serpapi_api_key` with your actual API key. Never commit your `.env` file or expose your API key publicly.

### Run Locally

Start the Flask application using the project's configured entry point. If running the backend module directly is supported, use:

```bash
py backend/app.py
```

Open the local URL printed in your terminal.

## 🌍 Live Deployment

Try FORESEEN here:

**[https://foreseen-nine.vercel.app/](https://foreseen-nine.vercel.app/)**

## 🎯 Vision

FORESEEN aims to make second-hand shopping more transparent by helping buyers understand not just the price of a product, but also the evidence behind that price.

**See beyond the price. Buy with confidence.**

## 👩‍💻 Author

**Bhavana S**

GitHub: [@bhavanaa-dev](https://github.com/bhavanaa-dev)

---

*FORESEEN — Better decisions start with better evidence.*

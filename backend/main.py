import sys

# Reuse the single source of truth for key resolution so the collector, the
# Flask app and this check all agree on the variable name and .env path.
try:
    from backend import shopping
except ImportError:
    try:
        from . import shopping
    except ImportError:
        import shopping


def main():
    try:
        shopping.get_api_key(required=True)
    except shopping.SerpApiError:
        print("Error: no SerpApi key found.")
        print("Please create a .env file (copy .env.example) and set SERPAPI_API_KEY.")
        sys.exit(1)
    else:
        print("SerpApi key is configured.")

if __name__ == "__main__":
    main()

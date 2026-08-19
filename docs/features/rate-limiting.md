# Rate Limiting

mockroute includes built-in per-IP rate limiting to prevent abuse and simulate real-world throttling.

## Configuration

Use the `--rate-limit` flag:

```bash
python mockroute.py --config routes.json --rate-limit 60  # 60 requests per minute per IP
```

Default: **100 requests per minute per IP**.

## How It Works

- Uses a sliding window of 60 seconds
- Each client IP is tracked independently
- Requests exceeding the limit receive a **429 Too Many Responses** response
- Thread-safe implementation using locks

## Example

```bash
# Allow 10 requests per minute
python mockroute.py --config routes.json --rate-limit 10

# Unlimited (set very high)
python mockroute.py --config routes.json --rate-limit 999999
```

## Response on Limit Exceeded

```json
{"error": "rate limit exceeded"}
```

With HTTP status code **429**.

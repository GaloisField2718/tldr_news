# TLDR Daily assets Worker

Read-only public delivery for immutable Daily WebP objects in the private R2 bucket. The Worker accepts only `GET` and `HEAD`, only for exact paths under `/daily/YYYY/MM/DD/<64-lowercase-hex>.webp`. It does not list, write, or delete objects. Missing/malformed/traversal paths return 404; other methods return 405.

Responses stream R2 bodies and include the stored content type, immutable one-year caching, ETag/conditional GET support, `nosniff`, and `Access-Control-Allow-Origin: *`. HEAD uses R2 `head` and has no body.

## Test

```bash
npm ci
npm test
```

Tests use a mocked binding and make no Cloudflare call.

## Manual deployment

1. Create the private `tldr-daily-assets` R2 bucket.
2. Review `wrangler.toml` (or copy `wrangler.toml.example`) and keep binding name `ASSETS`; change only safe Worker/bucket names if needed.
3. Authenticate Wrangler interactively or through an operational token outside Git.
4. Deploy manually:

```bash
cd cloudflare/tldr-assets-worker
npm ci
npx wrangler deploy
```

No CI job deploys this Worker. The resulting URL is normally:

```text
https://tldr-assets.<account-subdomain>.workers.dev/daily/YYYY/MM/DD/<sha256>.webp
```

Do not commit the account subdomain or credentials. No personal-domain DNS migration is required. Roll back with Wrangler's deployment/version rollback controls or deploy the prior Git revision. If a token is compromised, revoke it in Cloudflare, issue a bucket-restricted replacement, rotate the VPS secret, and inspect audit/activity logs.

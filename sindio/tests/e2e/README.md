# E2E Tests

## Setup

```bash
cd tests/e2e
npm install
npx playwright install
```

## Run tests

```bash
# Against local dev
npm run test:local

# Against staging
npm run test:staging

# Against production
npm run test:prod
```

## Structure

- `tests/dashboard.spec.ts` — Dashboard smoke tests
- `tests/feedback.spec.ts` — Feedback submission flow
- `tests/auth.spec.ts` — Authentication flow (when implemented)

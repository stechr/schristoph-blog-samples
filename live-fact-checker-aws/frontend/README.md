# Frontend — paste-and-check SPA

The simplest possible client for the fact-checker API: a static page (vanilla JS, no build step)
that calls `POST /v1/verify` and `POST /v1/extract` and renders verdict cards.

## Run

```bash
cp config.sample.js config.js          # then edit apiBase to your CDK ApiUrl output
python3 -m http.server 8000            # serve statically
# open http://localhost:8000
```

## Use

1. Pick a mode: **Verify a single claim** or **Extract claims from text**.
2. Paste a claim (or a transcript/document for extract mode).
3. Paste a **Cognito JWT** in the token field (PoC auth — see below).
4. **Check** → verdict cards (TRUE / FALSE / UNCERTAIN) with confidence, explanation, and cited
   sources with publication dates.

## Auth (PoC)

For the PoC you paste a Cognito JWT directly. Get one for a test user with the AWS CLI:

```bash
aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id <UserPoolClientId> \
  --auth-parameters USERNAME=<email>,PASSWORD=<password> \
  --region us-east-1
# use the IdToken from the response
```

A production client would obtain the token via the **Cognito Hosted UI** (or Amplify) instead of
pasting it.

> `config.js` is gitignored (it holds your account-specific API URL). Commit only
> `config.sample.js`.

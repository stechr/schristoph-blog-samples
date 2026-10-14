# Lambda Web Functions: waiting vs working

A plain Express app with three routes, used in the blog post
"Lambda Web Functions: What Changes When You Stop Paying for Waiting".

| Route | What it does |
|---|---|
| `/` | Returns a JSON hello |
| `/wait?ms=500` | Awaits a timer. Stands in for a database query, downstream API or model call |
| `/cpu?ms=50` | Spins the CPU synchronously. Stands in for rendering or JSON-heavy work |

The only Lambda-aware line reads the listen address from `AWS_LAMBDA_HTTP_ENDPOINT`
(`host:port`), which Lambda Web Functions set. Locally it falls back to `localhost:3000`.

## Run it locally

Requires Node.js 24 (the Web Functions runtime at launch is `nodejs24.x`).

```bash
npm install
npm start                                   # listening on localhost:3000
# in a second terminal:
node load.mjs http://localhost:3000 "/wait?ms=500" 50
node load.mjs http://localhost:3000 "/cpu?ms=50" 20
```

`load.mjs` fires N concurrent requests and prints how long the batch took. With one
Node process, 50 concurrent `/wait?ms=500` requests finish in roughly the time of one,
because the event loop is idle while each timer runs. 20 concurrent `/cpu?ms=50` requests
take roughly 20 x 50 ms, because each one blocks the event loop. That difference is the
whole cost story of Web Functions: waiting is cheap, working is metered.

## Deploy it as a Web Function

Needs an AWS CLI v2 release that includes the `aws lambda-web` commands (`aws lambda-web help`)
and a Region where Web Functions are available (at launch: US East (N. Virginia), US East (Ohio),
US West (Oregon), Asia Pacific (Tokyo), Europe (Ireland)).

```bash
npm ci --omit=dev
aws lambda-web deploy --name wait-demo --code . --region eu-west-1
# deploy asks for confirmation when it creates a new Web Function; add --create in scripts
```

The command creates (or reuses) a versioned S3 bucket and an execution role, creates the Web
Function, its first revision and a `dev` endpoint, and prints the HTTPS URL. Check the
endpoint's authentication type: with application-managed authentication Lambda forwards every
request to your app, so anyone with the URL can call it. Pass `--auth-type IamAuth` if you
want IAM-signed requests only.

If you pass your own bucket with `--bucket-name`, give it a bucket policy that allows the
`lambda.amazonaws.com` service principal `s3:GetObject` and `s3:GetObjectVersion` on the
package objects (scope it with an `aws:SourceAccount` condition); otherwise the deploy fails
with a validation error. Tags go in as repeated `--tags KEY=VALUE` options.

Then point the load script at the endpoint URL instead of localhost. Right after a deploy the
endpoint may answer part of a large burst with HTTP 429 while Lambda raises its dynamic
per-environment concurrency limit; send steady traffic for a few seconds before you measure.

CPU time per environment is in CloudWatch: namespace `AWS/Lambda/Web`, metric
`EnvironmentCPUTime`, dimension `FunctionName`.

## Clean up

```bash
aws lambda-web delete-web-function --function-name wait-demo --region eu-west-1
```

This removes the endpoints and revisions. It does not remove the execution role, the
deployment packages in the S3 bucket, or the CloudWatch Logs log groups. Delete those
separately if you no longer need them (there are two log groups:
`/aws/lambda/web/<name>` and `/aws/lambda/web/<name>.local`) (see the "Clean up" section of the developer guide).

## References

- Lambda Web Functions developer guide: https://docs.aws.amazon.com/lambda/latest/dg/web-functions.html
- Creating a Web Function: https://docs.aws.amazon.com/lambda/latest/dg/web-functions-create.html
- Lambda pricing (Web Functions section): https://aws.amazon.com/lambda/pricing/

## License

MIT-0

// Copy this file to config.js and fill in your deployed values (config.js is gitignored).
// apiBase  = the CDK `ApiUrl` output, e.g. https://abc123.execute-api.us-east-1.amazonaws.com/prod/
// clientId = the CDK `UserPoolClientId` output (Cognito app client, no secret)
window.CONFIG = {
  apiBase: "<API_URL_FROM_CDK_OUTPUT>",
  region: "us-east-1",
  clientId: "<USER_POOL_CLIENT_ID_FROM_CDK_OUTPUT>",
  wsBase: "ws://localhost:8765",   // optional: local live-streaming server for the Record feature
};

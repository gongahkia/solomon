# Cost Glance

`cost_glance` is the cloud spend module.

AWS uses Cost Explorer `GetCostAndUsage` for monthly `UnblendedCost`. The API endpoint is `https://ce.us-east-1.amazonaws.com`, the JSON RPC target is `AWSInsightsIndexService.GetCostAndUsage`, and the read-only IAM action is `ce:GetCostAndUsage`.

Minimal IAM policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ce:GetCostAndUsage",
      "Resource": "*"
    }
  ]
}
```

The local client wrapper can use `aws ce get-cost-and-usage --granularity MONTHLY --metrics UnblendedCost --output json`. This calls AWS and may expose account spend metadata to the configured AWS CLI profile.

GCP uses the Cloud Billing API `billingAccounts.list` for billing account discovery, and the local wrapper can use `gcloud billing accounts list --filter=open=true --format=json`. Google documents Cloud Billing cost and usage data export through BigQuery; querying exported spend is a separate `cost_glance` step.

Azure uses Cost Management Query Usage at `POST https://management.azure.com/{scope}/providers/Microsoft.CostManagement/query?api-version=2025-03-01`. The local wrapper uses `az rest` with a month-to-date `PreTaxCost` aggregation payload.

The daemon starts an off-thread hourly refresh loop. It writes `~/.local/state/shisa/cost.json` only when explicit provider inputs exist, such as `SHISA_COST_AWS_START` plus `SHISA_COST_AWS_END`, or `SHISA_COST_AZURE_SCOPE`.

The prompt renders cached values as `cost[provider:$amount]`, for example `cost[aws:$12.34 az:$5.67]`. Rendering reads the local cache only.

## Permissions And Privacy

- AWS: grant `ce:GetCostAndUsage` on `*` to the profile used by the daemon.
- GCP: grant a Cloud Billing role that can list billing accounts, such as Billing Account Viewer. Spend querying through BigQuery export also needs BigQuery read/query permissions on the export dataset.
- Azure: grant Cost Management data access for the queried scope. For Azure RBAC scopes, use a read-only role that can view cost data, such as Reader or Cost Management Reader.
- Privacy: refresh calls cloud billing APIs and stores account spend values in `~/.local/state/shisa/cost.json` with file mode `0600`. Prompt rendering does not call cloud APIs.

Sources: [AWS Cost Explorer API](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetCostAndUsage.html), [AWS CLI `ce get-cost-and-usage`](https://docs.aws.amazon.com/cli/latest/reference/ce/get-cost-and-usage.html), and [AWS IAM Service Authorization Reference for Cost Explorer](https://docs.aws.amazon.com/service-authorization/latest/reference/list_awscostexplorerservice.html).

GCP sources: [Cloud Billing APIs](https://docs.cloud.google.com/billing/docs/apis), [Cloud Billing REST reference](https://docs.cloud.google.com/billing/docs/reference/rest), [gcloud billing accounts list](https://docs.cloud.google.com/sdk/gcloud/reference/billing/accounts/list), and [Cloud Billing export to BigQuery](https://docs.cloud.google.com/billing/docs/how-to/export-data-bigquery).

Azure sources: [Cost Management Query Usage REST API](https://learn.microsoft.com/en-us/rest/api/cost-management/query/usage?view=rest-cost-management-2025-03-01) and [Azure CLI costmanagement reference](https://learn.microsoft.com/en-us/cli/azure/costmanagement?view=azure-cli-latest).

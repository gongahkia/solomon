# IaC Workspace

`iac_workspace` reads local project metadata only.

Terraform workspace resolution checks `.terraform/environment` first. If that file is absent or empty, it reads `.terraform/terraform.tfstate`, then `terraform.tfstate`, and returns `current_workspace` or `workspace` when present.

OpenTofu uses the same local workspace resolution as Terraform.

Pulumi stack resolution scans `~/.pulumi/workspaces/*.json` for the active stack whose `workDir` matches the current project directory. It then requires the matching `Pulumi.<stack>.yaml` file and returns the stack file name.

CDK workspace resolution reads `cdk.json` for the `app` command and `cdk.context.json` for the first cached context key when present.

# IaC Workspace

`iac_workspace` reads local project metadata only.

Terraform workspace resolution checks `.terraform/environment` first. If that file is absent or empty, it reads `.terraform/terraform.tfstate`, then `terraform.tfstate`, and returns `current_workspace` or `workspace` when present.

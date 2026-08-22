# Security Policy

Security fixes target `main` until a release branch exists. Report suspected vulnerabilities privately to angryapplegravy@gmail.com with the affected commit, platform, reproduction steps, and impact.

In scope:

- a target check that reports `verified` for a known-mismatched local invocation;
- parser behavior that lets an unsupported target override bypass a refusal;
- unsafe handling of a user-owned target configuration file;
- memory safety or command-execution defects in Shisa.

Shisa does not provide cloud authorization, credential isolation, remote Terraform backend validation, or Kubernetes admission control. Weaknesses in those external systems are outside this project's scope unless Shisa misreports their local inputs.

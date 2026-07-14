# Curator console

Seven server-rendered workflows form the operational console surface.

| Workflow | Purpose | Required role |
| --- | --- | --- |
| Verification Desk | Reaffirm, supersede, retire, or pin positions needing review. | `admin`, `reviewer`, or `lawyer` |
| Claims | Promote, reject, or defer source-extracted candidate claims. | `admin` or `curator` |
| Sources | Inspect health and sync history; sync filesystem sources and retry rejected extraction. | `admin` or `curator` |
| Reviews | Assign, start, and resolve authority-change review tasks. | `admin`, `reviewer`, or `lawyer` |
| Dependencies | Confirm or reject dependency suggestions and inspect the graph. | `admin` or `curator` |
| Currency Report | Filter movement by period and scope; export JSON or PDF. | any console read role |
| Audit Pack | Inspect evidence and export an item audit pack. | any console read role |

## Verification Desk

![Verification Desk](../assets/console/verification-desk.png)

[Animated walkthrough](../assets/console/verification-desk.gif)

## Dependency Review

![Dependency Review](../assets/console/dependency-review.png)

[Animated walkthrough](../assets/console/dependency-review.gif)

## Audit Pack

![Audit Pack](../assets/console/audit-pack.png)

[Animated walkthrough](../assets/console/audit-pack.gif)

## Screen notes

- [User guide](user-guide.md)
- [Verification Desk wireframe](verification-desk.md)
- [Dependency Review wireframe](dependency-review.md)
- [Currency Report wireframe](currency-report.md)
- [Audit Pack wireframe](audit-pack.md)
- [Stack decision](stack.md)

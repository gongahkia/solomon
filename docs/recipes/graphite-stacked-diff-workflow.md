# Stacked-Diff Workflow with Graphite + Shisa

Use Graphite for stack operations and Shisa for a fast local stack detector.

## 1. Initialize Graphite

Run Graphite setup once per Git repository:

```sh
gt init
```

Graphite stores its repository config under `.git/.graphite_repo_config`.

Check what Shisa sees:

```sh
shisa stack --cwd "$PWD"
```

Shisa's checked-in Graphite detector is marker-based and does not require the `gt` binary. It prints `provider: graphite` when it finds the marker shape it recognizes, otherwise `stack: none`. Use `gt log short` as the source of truth for Graphite's stack order.

## 2. Build the stack

Create the bottom branch:

```sh
gt checkout main
# edit files
gt create --all --message "feat(api): add user endpoint"
```

Create an upstack branch:

```sh
# edit files
gt create --all --message "feat(ui): consume user endpoint"
```

View tracked branches:

```sh
gt log short
```

`gt ls` is Graphite's default alias for `gt log short`.

## 3. Submit deliberately

Preview first:

```sh
gt submit --stack --dry-run
```

Submit after the preview matches the intended stack:

```sh
gt submit --stack
```

Add reviewers at submit time when useful:

```sh
gt submit --stack --reviewers alice
```

## 4. Address feedback mid-stack

Checkout the branch that needs edits, change files, then amend and restack descendants:

```sh
gt checkout feat/api-add-user-endpoint
# edit files
gt modify --all
gt submit --stack
```

To create a new commit instead of amending:

```sh
gt modify --commit --all --message "Responded to reviewer feedback"
```

## 5. Sync and clean up

Pull trunk, restack open branches, and handle merged or closed branch cleanup prompts:

```sh
gt sync
```

If sync reports conflicts, resolve them on the affected branch and continue with Graphite's restack flow:

```sh
gt restack
```

Open the current PR:

```sh
gt pr
```

See [VCS](../vcs/index.md), [Graphite Quick Start](https://graphite.com/docs/cli-quick-start), and [Graphite Command Reference](https://graphite.com/docs/command-reference).

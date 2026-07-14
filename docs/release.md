<!-- SPDX-License-Identifier: Apache-2.0 -->

# Python release runbook

The repository has two isolated publishing workflows:

- `.github/workflows/testpypi.yml` is manual-only and publishes an operator-selected ref to TestPyPI.
- `.github/workflows/release.yml` runs when a GitHub Release is published, verifies its tag is `v<project.version>`,
  uploads the built wheel and sdist to that release, then publishes the same artifacts to PyPI.

## One-time configuration

Create protected GitHub environments named `testpypi` and `pypi`; require an authorized reviewer for each.
Register these trusted publishers at the respective package index:

| Index | Owner | Repository | Workflow | Environment |
| --- | --- | --- | --- | --- |
| TestPyPI | `gongahkia` | `solomon` | `testpypi.yml` | `testpypi` |
| PyPI | `gongahkia` | `solomon` | `release.yml` | `pypi` |

Use a pending trusted publisher if the project does not yet exist on that index. The workflows use OIDC and do not
need stored package-index tokens.

## TestPyPI

Run the `TestPyPI` workflow manually and enter the exact commit, branch, or tag in `ref`. Approve the `testpypi`
environment after the build and installed-wheel CLI smoke test succeed. Verify the published package in a clean
environment before cutting a production release.

## PyPI

1. Update `project.version` and `CHANGELOG.md`, then merge the release commit.
2. Create and push the matching `v<project.version>` tag.
3. Create and publish the GitHub Release for that tag.
4. Approve the `pypi` environment after the build, version check, and release-asset upload succeed.

The package is not published merely by pushing a tag. The PyPI workflow starts only after publishing the GitHub
Release, and it fails before upload when its tag and `project.version` differ.

The TypeScript package remains unpublished pending npm scope/package ownership and release approval.

## npm

`@solomon/sdk` is release-ready but unpublished. `.github/workflows/npm-publish.yml` runs on a published GitHub
Release or a manually selected existing tag. It verifies that the tag is `v<package.version>`, runs the package tests
and pack dry-run, then requires the protected `npm` environment before OIDC publication.

Before the first publish, establish ownership of the `@solomon` scope and package on npm. Configure the package's npm
Trusted Publisher with owner `gongahkia`, repository `solomon`, workflow filename `npm-publish.yml`, environment
`npm`, and allowed action `npm publish`. npm documents that trusted-publisher configuration requires an existing
package; after initial package ownership is established, use the OIDC workflow rather than a stored publish token.

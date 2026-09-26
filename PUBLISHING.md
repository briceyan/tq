# Publishing

Push a `v*` tag matching `project.version` in `pyproject.toml` to publish to PyPI. The workflow runs checks, builds the wheel and source distribution, and publishes with OIDC; no PyPI token is needed.

## One-time setup

Configure a PyPI Trusted Publisher for `tq-json`:

- Owner: `briceyan`
- Repository: `tq`
- Workflow: `publish.yml`
- Environment: `pypi`

For the first upload, configure it as a pending publisher.

## Release

1. Update the version in `pyproject.toml` and run `uv lock`.
2. Commit and push the change to `main`.
3. Push the matching tag, for example:

   ```sh
   git tag v0.1.1
   git push origin v0.1.1
   ```

A GitHub Release is not required.

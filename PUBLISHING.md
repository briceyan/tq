# Publishing

The `publish.yml` workflow publishes `tq-json` to PyPI when a `v*` version tag is pushed. It verifies that the tag matches the version in `pyproject.toml`, runs checks and tests, builds the wheel and source distribution, then publishes them using PyPI Trusted Publishing (OIDC). No PyPI token is stored in GitHub.

## One-time PyPI setup

Configure a Trusted Publisher for `tq-json` with:

- Owner: `briceyan`
- Repository: `tq`
- Workflow: `publish.yml`
- Environment: `pypi`

If the project has not been published before, configure it as a pending publisher when creating the PyPI project.

The existing `v0.1.0` tag was used for the legacy `tq-query` distribution. Publish `tq-json` with a new version and matching tag, such as `0.1.1` / `v0.1.1`.

## Release a version

1. Update `project.version` in `pyproject.toml` and refresh `uv.lock` with `uv lock`.
2. Run the CI checks and commit the changes to `main`.
3. Create and push a matching version tag, for example:

   ```sh
   git tag v0.1.1
   git push origin v0.1.1
   ```

The tag push starts the publish workflow. A GitHub Release is not required.

# packaging/

What turns `dist/perfboard-studio` (built by `pyinstaller perfboard-studio.spec`) into the
files a person downloads. `.github/workflows/release.yml` runs all of it on a tag; the
ritual around it is in [docs/RELEASING.md](../docs/RELEASING.md).

| File | What it is |
| --- | --- |
| `perfboard-studio.nsi` | The Windows installer (NSIS, English and Turkish). |
| `appimage.sh` | The Linux AppImage. |
| `macos.sh` | The macOS disk image. |
| `check-bundle-models.sh` | Fails unless a built bundle carries every package mesh and its licence. Run by all three release jobs. |
| `check-mcp-stdio.py` | Fails unless a command serves a whole MCP session over stdio with nothing else on stdout. Run on every built bundle's `--mcp`, and by `tests/test_mcp_stdio.py` on the source. |
| `winget/` | A **draft** winget manifest for the current release. Not submitted. |
| `scoop/` | A **draft** Scoop manifest for the current release. Not submitted. |

## The package-manager drafts

`winget install Medinstech.PerfboardStudio` and `scoop install perfboard-studio` are one
line each and skip the browser, which is where an unsigned download meets its first
warning. Neither is published. Submitting puts the project in a public registry under an
identifier people will script against, so whether to do it, and when, is the owner's
decision. These files are ready for that decision and are not part of a release.

Both describe **0.22.0**, the newest release whose installer and `SHA256SUMS` exist. A
manifest for a release that does not exist yet cannot be checked against anything.

### winget

Three files, in the layout `winget-pkgs` wants under
`manifests/m/Medinstech/PerfboardStudio/<version>/`. Each field is read off
`perfboard-studio.nsi`, and that file says where they come from: the uninstall key is
`APP_NAME`, so that is the `ProductCode`; the installer elevates itself and installs for the
machine; it associates `.perf`; a silent install is NSIS's `/S`, and every message box in
the script answers itself under `/S`, so an upgrade over a running copy fails with an exit
code instead of waiting on a question nobody can see.

Before submitting:

```powershell
winget validate --manifest packaging\winget
winget install --manifest packaging\winget      # in Windows Sandbox, not on a dev machine
```

then a pull request to `microsoft/winget-pkgs` (`wingetcreate submit` does it). For a later
release, `wingetcreate update Medinstech.PerfboardStudio --version <v> --urls <Setup.exe URL>`
fills in the version, the URL and the hash.

### Scoop

One JSON file, for a bucket of the project's own (a repository named `scoop-bucket` with
the file under `bucket/`) or for `ScoopInstaller/Extras`. Scoop installs per user and never
elevates, so it does not run the installer: 7-Zip unpacks it. **Not yet tried**: no 7-Zip
was at hand where it was written. Try it with
`scoop install packaging\scoop\perfboard-studio.json` before anything else. If unpacking
the installer turns out fragile, the fix is a portable `.zip` beside the installer on each
release, which is a change to `release.yml` and the release's size, not to this file
alone. `checkver` and `autoupdate` read the version off GitHub's latest release and the
hash off its `SHA256SUMS`, so the manifest follows releases by itself once it is in a
bucket.

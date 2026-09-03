# toolboxmd marketplace

One catalog for ToolboxMD plugins. Codex, Claude Code, Grok Build, and Cursor
load host-native distributions from the same accepted Project releases.
Codex, Claude Code, and Grok Build add this marketplace, then install the
plugins they want:

- `karpathy-wiki@toolboxmd`
- `use-grok@toolboxmd`
- `agentsmd@toolboxmd`

A plugin repository is a plugin, not this marketplace. Do not path-install a
plugin checkout as the happy path.

## Add the marketplace

### Codex

```bash
codex plugin marketplace add toolboxmd/marketplace
```

### Claude Code

```json
{
  "extraKnownMarketplaces": {
    "toolboxmd": {
      "source": {
        "source": "github",
        "repo": "toolboxmd/marketplace"
      }
    }
  }
}
```

Then enable plugins as `karpathy-wiki@toolboxmd`, `use-grok@toolboxmd`, or
`agentsmd@toolboxmd`.

If you previously enabled `karpathy-wiki@karpathy-wiki-local` or
`agentsmd@agentsmd-local`, rename those keys to the `*@toolboxmd` form.

### Grok Build

```bash
grok plugin marketplace add toolboxmd/marketplace
```

Then install by name (trust hooks only from this publisher):

```bash
grok plugin install karpathy-wiki --trust
grok plugin install use-grok --trust
grok plugin install agentsmd --trust
```

Start a new session or reload plugins. Grok copies plugin files on install; a
later plugin release is not live until `grok plugin update <name>`.

## Install a plugin

After the marketplace is added:

```bash
codex plugin add karpathy-wiki@toolboxmd
codex plugin add use-grok@toolboxmd
codex plugin add agentsmd@toolboxmd
```

Uninstall is per plugin. Removing one plugin leaves the others installed.
Removing the marketplace is optional and host-specific. Wiki data, the wiki
pointer, and per-wiki runtime files survive uninstalling karpathy-wiki.

## Local sibling checkouts

For live checkouts next to each other (this machine: `karpathy-wiki`,
`use-grok`, `agentsmd` as siblings), generate host indexes from this catalog:

```bash
python3 scripts/render_catalog.py --local-root /path/to/sibling-root
```

Then add that sibling root as marketplace toolboxmd on each host. The generated
plugin set always matches this catalog. Do not hand-edit three JSON files into
three different lists. Do not nest plugins inside karpathy-wiki.

Codex local sources stay inside that sibling root (`./karpathy-wiki`, and so
on). Grok and Claude indexes for local-dev use the same names and in-root
paths.

## Refresh plugin pins

Published Codex, Claude Code, and Grok Build sources are pinned to the full
commit SHA recorded in `catalog.json`. A tagged release may also record its tag
in `release`; Codex and Claude then verify both selectors. After a plugin
release is on GitHub, set or update `release` when applicable, then run:

```bash
python3 scripts/refresh_pins.py
```

Commit the updated `catalog.json` and rendered indexes. Entries without a
`release` resolve the repository `HEAD` only when this explicit refresh command
runs.

## Ingest a released Project Record

Project Record v1 lets a released Project point to its existing authoritative
version, delivery, Skill, documentation, requirement, and proof files without
copying those facts into Marketplace.

After the Project publishes a conforming immutable release, run:

```bash
python3 scripts/ingest_project.py <project-id> <release-tag>
```

The command reads repository membership from `catalog.json`, resolves the exact
tag, validates the record and every referenced file from the same Git tree, and
only then updates the catalog and all three host indexes. See
[`docs/project-record-v1.md`](docs/project-record-v1.md) for the contract,
deterministic local acceptance, and delivery-state boundaries.

## Generate the AgentsMD Cursor Plugin

Generate the Cursor multi-plugin manifest and the AgentsMD package from the
accepted `catalog.json` release:

```bash
python3 scripts/render_cursor.py agentsmd
```

For deterministic offline proof against an existing exact Git source, add
`--source /path/to/agentsmd`. The command verifies the accepted release commit
and Project Record digest before replacing generated output. It copies the
complete active Skill directories, required `versionctl` runtime, licences,
and provenance from that release and writes the source hashes to
`plugins/agentsmd/SOURCE.json`.

The Cursor package intentionally does not include AgentsMD's global
`AGENTS.md`, lifecycle hooks, or the Project Direction hook executable. Those
behaviors require separate host-level proof. The package exposes the released
Skills and their required resources only.

Validate the result with the current official
[`cursor/plugin-template`](https://github.com/cursor/plugin-template)
validator before local installation or submission.

## Add a plugin

1. Give the plugin repo Codex, Claude, and Grok plugin manifests. Name is the
   short plugin id (`use-grok`, not `toolboxmd-use-grok`). Version mirrors
   that repo's `VERSION`.
2. Add one object to `catalog.json` (`name`, `description`, `github`, `sha`,
   `category`).
3. Run `python3 scripts/render_catalog.py` and the test suite.
4. Add one line to this README's plugin list.

No new marketplace name. Eligible later without a spec rewrite:
building-agentskills, codex-adapter, html-skill, and future public plugin
repos under github.com/toolboxmd.

## Test

```bash
bash tests/run-all.sh
```

## Bootstrap Toolybara

Toolybara's credential-independent policy, guided bootstrap, and proof contract
are documented in
[`docs/toolybara-bootstrap.md`](docs/toolybara-bootstrap.md). The provisioning
wizard is intentionally not run during ordinary development or tests. It
creates the GitHub App, installation, organization Actions variable, and
organization Actions secret only when a human explicitly runs it:

```bash
scripts/bootstrap_toolybara.sh
```

The wizard does not configure branch protection, rulesets, native auto-merge,
automatic branch deletion, bypass actors, or any other repository setting.

## Layout

- `catalog.json` is the source of truth for membership and Grok pins.
- `schemas/project-record-v1.schema.json` defines the minimal released record.
- `scripts/ingest_project.py` validates and accepts one immutable release.
- `.agents/plugins/marketplace.json` is the Codex index.
- `.claude-plugin/marketplace.json` is the Claude Code index.
- `.grok-plugin/marketplace.json` is the Grok Build index.
- `.cursor-plugin/marketplace.json` is the generated Cursor multi-plugin index.
- `plugins/agentsmd/` is the generated Cursor-native AgentsMD package.
- `scripts/render_catalog.py` writes those indexes (and local-dev indexes).
- `scripts/render_cursor.py` validates provenance and writes Cursor output.

## Version

`VERSION` is canonical. This repository versions the catalog and ingestion
contract, not the Projects it distributes.

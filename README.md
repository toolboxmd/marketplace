# toolboxmd marketplace

One catalog for ToolboxMD plugins. Codex, Claude Code, and Grok Build add this
marketplace, then install the plugins they want:

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

## Refresh Grok pins

Published Grok sources are git URLs pinned to a full commit sha. After a plugin
release is on GitHub:

```bash
python3 scripts/refresh_pins.py
```

Commit the updated `catalog.json` and rendered indexes.

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

## Layout

- `catalog.json` is the source of truth for membership and Grok pins.
- `.agents/plugins/marketplace.json` is the Codex index.
- `.claude-plugin/marketplace.json` is the Claude Code index.
- `.grok-plugin/marketplace.json` is the Grok Build index.
- `scripts/render_catalog.py` writes those indexes (and local-dev indexes).

## Version

0.1.1. This repository versions the catalog, not the plugins.

# Project Record v1

Project Record v1 is a minimal index over authoritative facts in one released
Project Git tree. Marketplace owns the schema. Each Project owns its record at
`.toolboxmd/project.json`.

The immutable schema identifier is:

```text
https://raw.githubusercontent.com/toolboxmd/marketplace/v0.3.0/schemas/project-record-v1.schema.json
```

## Why each field exists

| Field | Why the record owns it |
| --- | --- |
| `$schema` | Selects the exact immutable validation contract. |
| `id` | Connects the released tree to curated Marketplace membership. |
| `kind` | Tells Marketplace which distribution role the Project has. |
| `outcome` | Gives agents one vendor-neutral, outcome-oriented discovery statement. |
| `factSources` | Points to existing released owners without copying their facts. |

`factSources.version` points to the canonical version file.
`factSources.delivery` maps supported harness names to their native manifests.
The optional `skills`, `documentation`, `requirements`, and `proof` arrays point
to the files that own those facts when a delivery manifest does not already own
them.

The record does not contain its repository URL, release tag, commit SHA,
manifest fields, Skill fields, or documentation content. Marketplace supplies
curated membership and the requested release ref, resolves the ref to its
peeled commit, and records that provenance with the record digest in
`catalog.json`.

## Manual ingestion

After a Project publishes a conforming immutable release, run from the
Marketplace repository:

```bash
python3 scripts/ingest_project.py <project-id> <release-tag>
```

The command derives the GitHub repository from `catalog.json`, clones it, and
resolves the exact tag. For deterministic local acceptance only, supply an
equivalent local Git repository:

```bash
python3 scripts/ingest_project.py <project-id> <release-tag> \
  --source /path/to/project-git-repository
```

The command reads the record and every referenced source directly from the
peeled commit. It validates identity, version, paths, and native manifests and
builds the complete candidate catalog and host indexes before replacing any
accepted file. A rejected candidate leaves `catalog.json` and every generated
index byte-identical.

On success, inspect the diff, run `bash tests/run-all.sh`, and complete the
repository version and release workflow. Ingestion and rendering prove accepted
Marketplace publication data. They do not prove provider submission,
installation, loading, or a representative agent outcome.

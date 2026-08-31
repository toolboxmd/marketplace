# Agent discovery and distribution surfaces

Date: 2026-08-30

Status: Primary-source research supporting the current Marketplace Objective

## Question

How should ToolboxMD Projects be discovered, understood, installed, loaded, and
proved across Codex, Claude Code, Grok Build, Cursor, the open Agent Skills
ecosystem, and public web discovery?

## Findings

No single current standard owns the complete path from public discovery to a
working agent outcome. The Agent Skills specification defines a portable Skill
package. Each agentic harness adds its own discovery, package, installation,
review, update, and loading behavior. Public directories add another lifecycle
with their own submission and review states.

The resulting system needs one released Project Record as product truth,
generated host-native adapters as distribution views, and separate proof for
each stage of the Discovery Funnel. Repository publication alone is not proof
that a Project is discoverable, installed, loaded, or outcome-ready.

### OpenAI and Codex

- OpenAI describes one Plugins Directory shared by ChatGPT and Codex. Codex can
  also discover installed standalone Skills and select them from their
  descriptions or explicit invocation. [Plugins](https://learn.chatgpt.com/docs/plugins)
  and [Build Skills](https://learn.chatgpt.com/docs/build-skills) document these
  separate package and selection surfaces.
- A Codex plugin has discovery metadata beyond a starter prompt, including
  name, version, description, author, repository, keywords, display copy,
  category, capabilities, assets, and prompts. These fields should describe
  concrete outcomes and selection boundaries. [Build plugins](https://developers.openai.com/plugins/build/plugins)
  defines the package and manifest surface.
- Public submission is a reviewed snapshot with listing copy, assets, support
  and policy links, regions, release notes, and positive and negative test
  cases. A repository release does not by itself update the public directory.
  [Plugin submission](https://developers.openai.com/plugins/deploy/submission)
  defines that lifecycle.
- OpenAI recommends direct, indirect, and negative prompts to measure metadata
  precision and recall. This supports an outcome-oriented Agent Search
  Optimization benchmark rather than keyword volume alone. [Optimize metadata](https://developers.openai.com/plugins/guides/optimize-metadata)
  provides the testing model.
- OpenAI does not document a public ranking formula or establish that
  `llms.txt`, skills.sh, or general web SEO changes native Plugins Directory
  ranking. Those effects must remain unknown until measured.

### Claude Code

- Claude Code custom marketplaces use `.claude-plugin/marketplace.json` and can
  reference immutable Git sources. Anthropic recommends pinning third-party
  sources to exact revisions for trust and reproducibility. [Plugin
  marketplaces](https://code.claude.com/docs/en/plugin-marketplaces) and the
  [plugin reference](https://code.claude.com/docs/en/plugins-reference) define
  the host contract.
- Installed Skills are selected from their description and `when_to_use`
  guidance after installation. Metadata therefore needs both positive outcome
  language and clear non-selection boundaries. [Agent Skills](https://code.claude.com/docs/en/skills)
  documents selection behavior.
- Claude Code exposes custom, community, and Anthropic-managed discovery
  surfaces. Public community or official visibility is a separate publication
  path, not a side effect of a Git tag. The [community marketplace](https://github.com/anthropics/claude-plugins-community)
  and [official marketplace](https://github.com/anthropics/claude-plugins-official)
  are distinct sources.
- Plugin version participates in update and cache behavior. Changing only a
  source SHA without the corresponding package version can leave consumers on
  cached content. Release identity must therefore bind version and immutable
  source together.
- Anthropic does not publish a general public marketplace ranking formula.
  Keywords and tags improve retrievability, but ranking claims remain unknown.

### Grok Build

- Grok Build discovers Skills from Grok, Agent Skills, and compatible project
  or user locations. Skills can appear as slash commands and can be selected
  automatically from `description` and `when-to-use`. [Grok Skills](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/08-skills.md)
  documents these surfaces.
- Grok plugins use a native `.grok-plugin/marketplace.json`. An optional
  `plugin-index.json` can expose component previews before installation. [Grok
  plugins](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/09-plugins.md)
  defines installation and update behavior.
- The official xAI Marketplace requires remote entries to use a full 40-character
  commit SHA. Its keywords and domains support proactive plugin discovery and
  should be product-scoped to avoid irrelevant recommendations. The [xAI
  plugin marketplace](https://github.com/xai-org/plugin-marketplace) and its
  [contribution guide](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md)
  define that publication path.
- Grok exposes explicit marketplace and plugin update commands. The reviewed
  sources do not prove automatic background updates, so update availability and
  installed state must be reported separately.

### Cursor

- Cursor supports Agent Skills in `.agents/skills`, `.cursor/skills`, and
  compatible user or project locations. The agent can select a Skill from its
  name and description, while explicit invocation and path restrictions allow
  tighter control. [Cursor Agent Skills](https://cursor.com/docs/skills)
  documents selection and compatibility.
- Cursor supports the open Agent Plugin form and a richer Cursor Plugin package
  using `.cursor-plugin/plugin.json`. [Cursor plugins](https://cursor.com/docs/reference/plugins)
  defines the package surface.
- Cursor has a public Marketplace and a Customize discovery experience. Users
  can install through the interface or `/add-plugin`. [Customize Cursor](https://cursor.com/docs/customize-cursor),
  [Plugins](https://cursor.com/docs/plugins), and [plugin help](https://cursor.com/help/customization/plugins)
  document these user paths.
- Cursor's multi-plugin repository pattern uses a root
  `.cursor-plugin/marketplace.json` and repository-local plugin sources. The
  [Cursor plugin template](https://github.com/cursor/plugin-template) is the
  primary implementation example.
- Public Cursor updates are reviewed. The reviewed documentation does not prove
  immutable source enforcement for installed public packages or autonomous
  public Marketplace search from an unnamed outcome prompt. ToolboxMD must keep
  its own upstream tag, commit SHA, and digest as provenance and prove actual
  fresh-install behavior.

### Agent Skills and skills.sh

- The Agent Skills specification defines the Skill directory, `SKILL.md`
  frontmatter, progressive disclosure, and optional resources. It does not
  define a registry, installer, update protocol, package version, or universal
  repository layout. [Agent Skills specification](https://agentskills.io/specification)
  is the owning standard.
- `.agents/skills` is an interoperability convention used by several hosts. It
  is not itself a requirement of the Agent Skills package specification.
- A conforming client discovers candidate Skills and can select them from
  metadata. Description quality should be tested with positive and negative
  task prompts across repeated runs. [Adding Skills support](https://agentskills.io/client-implementation/adding-skills-support)
  and [optimizing descriptions](https://agentskills.io/skill-creation/optimizing-descriptions)
  define those practices.
- Vercel's `skills` CLI is a cross-host installer, not part of the Agent Skills
  standard. It supports repository, local, and direct sources, project or
  global targets, and host-specific destinations including Cursor and Grok.
  Its lock data records source, reference, and content hash, but mutable
  references remain mutable upstream. The [Vercel Skills CLI](https://github.com/vercel-labs/skills/blob/main/README.md)
  documents this behavior.
- `/.well-known/agent-skills/index.json` is a Vercel ecosystem extension. It is
  useful machine-readable discovery, but ToolboxMD must not present it as part
  of the Agent Skills standard.
- skills.sh indexes eligible public GitHub Skills after CLI installation
  telemetry. Its search API uses Skill name, source, and description, with
  different matching behavior for single-word and multi-word queries.
  [skills.sh FAQ](https://skills.sh/docs/faq) and [search API](https://skills.sh/docs/api)
  document eligibility and search.
- `skills.sh.json` groups presentation. It does not change the underlying Skill
  package contract. [skills.sh customization](https://skills.sh/docs/customize)
  defines that extension.
- skills.sh does not publish a ranking formula or a self-service process for
  guaranteed official curation. Inclusion and position must be observed, not
  promised.

### One-command precedent

Matt Pocock's Skills repository demonstrates one stable identity with
host-native installation for Claude and `npx skills@latest add
mattpocock/skills` for other supported hosts. Its value is a common front door,
machine-readable packages, focused Skill pages, and host adapters, not one
universal installed artifact. See the repository [README](https://github.com/mattpocock/skills/blob/6654f6b60cd9d5be8b54c6fafe44346dabeb3b76/README.md)
and [install guidance](https://github.com/mattpocock/skills/blob/6654f6b60cd9d5be8b54c6fafe44346dabeb3b76/.agents/install-block.md).

ToolboxMD should keep the useful pattern while tightening provenance and
autonomy. The bootstrap route should resolve an approved immutable release,
detect the host, avoid duplicate native-plugin and copied-Skill installations,
request one explicit trust grant, and then allow authorized configuration and
updates.

## Distribution model implied by the evidence

1. Each ToolboxMD Project owns its Project Record, release artifact, detailed
   documentation, verification, and runtime deployment.
2. ToolboxMD Marketplace ingests approved immutable Project Records for Agent
   Modules. It owns workflow membership, host adapters, Agent Search
   Optimization, bootstrap installation, generated indexes, and distribution
   proof.
3. `toolbox.md` presents canonical Project pages, cross-Project navigation, and
   machine-readable public discovery.
4. A successful Project release proposes an exact Marketplace update. Scheduled
   reconciliation detects missed events and drift.
5. An invalid update preserves the last known-good publication and exposes the
   blocker.
6. Submission, approval, publication, availability, installation, loading, and
   outcome proof remain distinct lifecycle states.

This is a federated, one-way publication model. A separate distribution service
is unnecessary until persistent state, secrets, independent availability,
multiple non-Marketplace consumers, or separate ownership create a real
boundary.

## Agent Search Optimization benchmark

Test every public Project against at least five query classes on every claimed
surface:

1. Product-name query: the user or agent already knows `AgentsMD`.
2. Unnamed-outcome query: the user describes the result but not the product.
3. Capability query: the user asks for a specific capability supplied by one
   Skill or Agent Module.
4. Workflow query: the user asks for a multi-step outcome requiring several
   ToolboxMD capabilities.
5. Negative query: the Project should not be selected.

For each class, record whether the Project is discoverable, correctly
understood, installable under the granted authority, loaded in a fresh session,
and able to complete a representative real task. Repeat probabilistic selection
tests and report precision and recall separately from installation success.

## Unknowns that require live proof

- Native provider ranking behavior beyond documented metadata fields.
- Review acceptance and publication time for each public provider directory.
- Whether a fresh agent can find the public Project from an unnamed outcome
  without prior Marketplace installation.
- Cursor's effective immutable-version behavior after public installation and
  update.
- skills.sh inclusion timing, position, and practical search recall.
- Whether the bootstrap route can configure every host autonomously without
  violating host permission and trust controls.

These unknowns are acceptance-test inputs. They are not reasons to weaken the
Objective or claim unsupported publication state.

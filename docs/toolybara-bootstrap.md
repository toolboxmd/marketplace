# Toolybara bootstrap

This runbook defines the one-time Human Gate for Toolybara. The repository
contains the repeatable wizard and deterministic validation, but authoring,
testing, merging, or releasing those files does not create the GitHub App,
install it, generate a key, write a secret or variable, or change repository
settings.

Run the wizard only from a trusted Cavallo checkout after reviewing
[`toolboxmd/marketplace#16`](https://github.com/toolboxmd/marketplace/issues/16):

```bash
scripts/bootstrap_toolybara.sh
```

Do not run it end to end in CI. It pauses for browser work and Human Gates.

## Ordered stages and values

| Stage | Machine and person | Exact URL or command path | Values captured | Secret | Destination |
|---|---|---|---|---|---|
| 1. Preflight and settings baseline | Cavallo, human operator | `gh auth status`; `gh auth refresh --hostname github.com --scopes admin:org` only if needed; `python3 scripts/verify_toolybara_bootstrap.py static`; `python3 scripts/verify_toolybara_bootstrap.py capture-settings` | Current Marketplace settings snapshot | No | Local ephemeral files removed when the wizard exits |
| 2. Register Toolybara | Cavallo browser, human operator | Existing App: `https://github.com/organizations/toolboxmd/settings/apps/toolybara`; new App: `https://github.com/organizations/toolboxmd/settings/apps/new?name=Toolybara&description=The%20ToolboxMD%20release%20courier.%20Toolybara%20carries%20verified%20ToolboxMD%20releases%20into%20the%20Marketplace%20and%20merges%20them%20when%20every%20check%20is%20green.&url=https%3A%2F%2Fgithub.com%2Ftoolboxmd%2Fmarketplace&public=false&webhook_active=false&contents=write&pull_requests=write` | App ownership, name, slug, description, homepage, visibility, webhook state, permission map, and redacted settings evidence | No | GitHub App registration; redacted evidence prepared outside the repository for the later Issue #16 proof handoff |
| 3. Install on Marketplace only | Cavallo browser, human operator | `https://github.com/organizations/toolboxmd/settings/installations`; if absent, `https://github.com/apps/toolybara/installations/new` | Organization and selected repository list | No | One `toolboxmd` installation with only `toolboxmd/marketplace` selected |
| 4. Store the public client ID | Cavallo browser and shell, human operator | `https://github.com/organizations/toolboxmd/settings/apps/toolybara`; copy Client ID from About; `gh variable set TOOLYBARA_CLIENT_ID --org toolboxmd --repos agentsmd,marketplace --body "$TOOLYBARA_CLIENT_ID"` | `TOOLYBARA_CLIENT_ID` | No | One organization Actions variable selected only for `agentsmd` and `marketplace` |
| 5. Store the private key | Cavallo browser and shell, human operator | `https://github.com/organizations/toolboxmd/settings/apps/toolybara`; under Private keys select Generate a private key; `printf '%s' "$TOOLYBARA_PRIVATE_KEY" \| gh secret set TOOLYBARA_PRIVATE_KEY --org toolboxmd --repos agentsmd,marketplace` | Absolute PEM path and PEM contents | Yes | One organization Actions secret selected only for `agentsmd` and `marketplace`; PEM remains local only until stage 7 |
| 6. Verify Toolybara identity and scope | GitHub-hosted runner dispatched by the Cavallo operator | `gh workflow run toolybara-bootstrap-verification.yml --repo toolboxmd/marketplace --ref main` | Workflow run URL, Toolybara slug, registered App metadata, effective installation permission inventory, actual installation repository list, and Marketplace token scope | Both tokens and the App JWT are secret and ephemeral | A Marketplace-only Contents and Pull requests write token and an installation-wide Metadata read audit token exist only inside the job and are revoked by the pinned token actions; the App JWT exists only in the verification step; redacted proof goes to the job summary |
| 7. Prove settings unchanged and clean up | Cavallo, human operator | Wizard-managed snapshots: `python3 scripts/verify_toolybara_bootstrap.py capture-settings > "$AFTER_SETTINGS"`; `python3 scripts/verify_toolybara_bootstrap.py compare-settings "$BEFORE_SETTINGS" "$AFTER_SETTINGS"`; `python3 scripts/verify_toolybara_bootstrap.py credential-metadata`; confirmed local PEM removal | After snapshot and credential metadata without values | PEM remains secret until deletion | Evidence in terminal and GitHub workflow summary; no durable local credential |

The stage order is binding. Registration precedes installation. Installation
precedes key generation. Credential writes precede token proof. The local PEM
is removed only after proof passes.

## Exact App contract

The canonical machine-readable contract is
[`toolybara/bootstrap-policy.json`](../toolybara/bootstrap-policy.json).

- Owner: `toolboxmd` organization.
- Name and slug: `Toolybara`, `toolybara`.
- Expected bot actor: `toolybara[bot]`.
- Visibility: private.
- Webhook: inactive. The design does not host a webhook receiver.
- Installation: selected-repository access to `toolboxmd/marketplace` only.
- Repository permissions: Metadata read-only, Contents read and write, Pull
  requests read and write.
- Organization permissions: none.
- Account permissions: none.
- Event subscriptions: none.
- Every other repository permission: No access.

GitHub recommends selecting the minimum App permissions. Contents write is
required for creating or updating the promotion branch, sending the
`repository_dispatch` event to Marketplace, and merging the exact pull-request
head. Pull requests write is required to create or update the promotion pull
request. Metadata read-only is the baseline repository metadata permission.

Contents write is repository-wide. GitHub App permissions do not restrict it
to one branch or generated-file allowlist. Toolybara therefore has technical
capability inside Marketplace that is broader than the intended behavior. The
trusted workflows must enforce the expected actor, branch, pull request, exact
head SHA, generated-file allowlist, candidate identity, catalog validity, and
version transition before minting or using a write token. The App has no
Administration permission, so it cannot change repository settings.

## Event path and credential boundary

An AgentsMD workflow's built-in `GITHUB_TOKEN` is limited to AgentsMD and
cannot call Marketplace's repository-dispatch endpoint. That endpoint requires
Contents write on Marketplace. Without a separate token broker, AgentsMD must
be allowed to use Toolybara's private key to mint a short-lived Marketplace
installation token.

The narrowest current arrangement is one organization secret, not two
repository-secret copies:

- `TOOLYBARA_PRIVATE_KEY`: organization secret, selected only for `agentsmd`
  and `marketplace`.
- `TOOLYBARA_CLIENT_ID`: organization variable, selected only for `agentsmd`
  and `marketplace`.

Toolybara remains installed only on Marketplace. The future AgentsMD release
workflow must request a token explicitly restricted to the `marketplace`
repository and only the permissions needed for dispatch. Marketplace must
independently resolve all release facts because dispatch payload data is only a
wake-up hint. Scheduled reconciliation remains mandatory because scheduled or
event runs can be delayed or missed.

If exposing the private key to the AgentsMD workflow is later judged too broad,
the alternatives are a dedicated external signing broker or abandoning the
independent event path. The broker adds a new service and operational boundary.
Schedule-only reconciliation does not meet the current Objective.

## Repository settings that must not change

The wizard captures before and after snapshots and rejects any difference. The
approved baseline is:

- default branch `main`;
- no branch protection;
- no repository rulesets;
- native auto-merge disabled;
- automatic branch deletion disabled.

With no branch protection or rulesets, no required-status-check setting,
blocked direct or force push rule, or bypass actor exists. The wizard contains
no repository-settings write endpoint or `gh repo edit` command.

## Verification

Credential-independent proof:

```bash
python3 scripts/verify_toolybara_bootstrap.py static
bash tests/run-all.sh
```

Credential-bound proof begins only after the Human Gate. The manually
dispatched workflow is restricted to `main` and pins every external action to
a full commit SHA. It mints one Marketplace-only token with Contents write and
Pull requests write for the future behavioral path, plus one installation-wide
Metadata read token that can audit the actual installation repository list.
It also creates a masked, in-memory App JWT to read App and installation
metadata using GitHub's required Bearer authentication. It verifies the
`toolybara` app slug, registered App metadata and permissions, organization
owner, selected-repository mode, effective installation permission inventory,
actual single-repository installation scope, and Marketplace-only functional
token scope without performing a write. Both installation tokens are revoked
by their pinned actions after the job.

The wizard then verifies the organization secret and variable metadata without
reading the secret value. It requires exactly two selected repositories for
each organization credential and rejects repository-level copies in either
repository. It also compares the before and after settings snapshots and asks
before deleting the local PEM.

Static validation checks the exact stage order and destination commands, the
unchanged canonical wizard library, policy and workflow permissions, selected
repository sets, prohibited settings mutations, and high-signal private-key,
GitHub App client-ID, and GitHub token patterns across tracked files.

## Authority split

Approval to author, review, merge, and release this repeatable wizard permits
only repository files, deterministic tests, the verification workflow, and
documentation. It does not provision Toolybara.

Later running `scripts/bootstrap_toolybara.sh` authorizes the operator-guided
actions shown in the seven stages: refresh the local `gh` OAuth grant with
`admin:org` if required, create or reuse the exact private Toolybara App,
install it only on Marketplace, generate one private key, upsert the selected
organization variable and secret, dispatch the read-only verification run,
and remove the downloaded PEM after successful proof. It does not authorize
repository settings changes, #17 promotion implementation, a Marketplace
merge, a Marketplace release, provider publication, installation into an
agentic harness, or deployment.

## Official GitHub references

- [Registering a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app)
- [Registering a GitHub App using URL parameters](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-using-url-parameters)
- [Choosing permissions for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app)
- [Installing a GitHub App](https://docs.github.com/en/apps/using-github-apps/installing-a-github-app-from-a-third-party)
- [Using a GitHub App in Actions](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/making-authenticated-api-requests-with-a-github-app-in-a-github-actions-workflow)
- [Generating a JSON Web Token for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app)
- [Managing private keys](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps)
- [Creating a repository dispatch event](https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event)
- [Creating and merging pull requests](https://docs.github.com/en/rest/pulls/pulls)
- [Workflow events and schedules](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [Organization Actions secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets#creating-secrets-for-an-organization)

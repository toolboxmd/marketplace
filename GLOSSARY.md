# Glossary

## Project

An independently owned, versioned, and released ToolboxMD unit. An App and an
Agent Module are both Projects.

Avoid using `App`, `Plugin`, `Skill`, or `Product` as a synonym for every
Project.

## App

A Project with a standalone runtime that humans or agents operate directly. A
graphical interface is common but not required.

An App remains a Project. A Project without a graphical interface is not
automatically an Agent Module.

## Agent Module

A Project installed into an agentic harness to extend what the harness can do.

Use `Agent Module`, not `Workflow Module`, when this installation role matters.

## Skill

One agent capability defined by a `SKILL.md` package and selected explicitly or
from task context. A Skill may be one component of an Agent Module.

Do not use `Skill` as a synonym for its containing Project or plugin package.

## Agentic Harness

A host that loads agent instructions, Skills, plugins, tools, or related
capabilities. Current target harnesses are Codex, Claude Code, Grok Build, and
Cursor.

## ToolboxMD Agentic Workflow

The curated ToolboxMD core and optional Agent Modules that work together to help
an agent turn intent into outcomes.

## ToolboxMD Marketplace

The discovery and distribution system for ToolboxMD Agent Modules. It owns
workflow composition, host adapters, release ingestion, Agent Search
Optimization, installation, and distribution proof.

## ToolboxMD Directory

The public cross-Project discovery experience on `toolbox.md`. It presents Apps,
Agent Modules, Skills, and other public Projects without owning their detailed
implementation documentation.

## Project Record

A minimal machine-readable index released by a Project. It identifies the
Project, states the outcome it provides, and points to the released files that
own version, delivery, Skill, documentation, requirement, and proof facts.

The Project Record does not duplicate facts that already have an authoritative
owner in the same released Git tree. Marketplace supplies and records the
immutable release provenance.

## Agent Search Optimization

The work of making a Project retrievable, understandable, correctly selected,
and actionable when an agent searches by product name, desired outcome,
capability, or workflow.

## Discovery Funnel

The five independently proved states of publication: discoverable,
understandable, installable, loadable, and outcome-ready.

## Bootstrap Installer

The stable ToolboxMD entry point that detects the agentic harness and installs
the approved core through host-native adapters after the required trust grant.

## Publication

The state in which an exact released Project is visible and usable through a
named distribution surface. Submission, approval, publication, installation,
and loading are separate states.

## Toolybara

The private ToolboxMD GitHub App that carries validated immutable Agent Module
releases into Marketplace through one expected promotion branch and pull
request. It is installed only on `toolboxmd/marketplace` and uses a trusted
final workflow job to merge an exact revalidated head.

Do not use `Toolybara` for GitHub Actions generally, a human account, or an
agent with authority outside Marketplace promotion.

## Eligible Release

The newest published stable AgentsMD release whose peeled tag commit, Project
Record, record digest, referenced facts, and required proof all pass the
Marketplace acceptance contract.

A release named in an event is not eligible until Marketplace resolves and
validates it independently.

## Wake Hint

An untrusted release tag sent by an AgentsMD event only to start Marketplace
reconciliation. It never selects or proves the release that Marketplace
promotes.

## Generated Promotion Pull Request

The Toolybara-authored pull request from `toolybara/promote-agentsmd` that
contains only deterministic AgentsMD distribution output and one Marketplace
patch transition.

Do not use this term for a human-authored publication proposal such as pull
request #15.

## Trusted Final Job

The Marketplace workflow job that reruns candidate validation against live
state, binds the exact pull-request head, and uses a fresh Toolybara token for
the SHA-bound merge and corresponding Marketplace release.

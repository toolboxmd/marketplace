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

A machine-readable record released by a Project. It states identity, version,
immutable source, outcomes, capabilities, delivery forms, dependencies,
permissions, documentation, compatibility, and proof.

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

---
name: update-local-memory
description: Automatically update fcpp_bridge's local MEMORY under claude_code/ folder based on session discoveries
keywords:
  - memory
  - documentation
  - knowledge-base
  - automation
  - update-findings
---

# Skill: Update Local MEMORY Automatically

## Purpose

Maintain `fcpp_bridge/claude_code/MEMORY.md` and its indexed files synchronously with discoveries made during the current session, without requiring manual instruction each time.

## Invocation

Called automatically when:

- Session ends with significant discoveries
- User says "update MEMORY" or "save findings"
- Major technical issue resolved or pattern discovered

## Process

### Step 1: Identify Discoverable Facts

Scan for:

- **Root causes** solved (e.g., "include path must be lib/fcpp.hpp")
- **Environment findings** (e.g., "FCPP_INCLUDE_PATH must be set before each shell session")
- **Code patterns** (e.g., "call all primitives before match/case block")
- **Build/run commands** (e.g., "python -m fcpp_bridge.examples.name")
- **Dependencies** (e.g., "requires g++ 14+ with C++14 support")
- **File structure** (e.g., "generated C++ goes to cpp_transpiled/")
- **Workarounds** (e.g., "if compilation fails, check FCPP_INCLUDE_PATH")

### Step 2: Determine File Location

Choose destination based on category:

| Category                        | File                            | Pattern                       |
| ------------------------------- | ------------------------------- | ----------------------------- |
| Project structure + build facts | `memory_indexes/project_*.md`   | State, run commands, env vars |
| User preferences + feedback     | `memory_indexes/feedback_*.md`  | Style, preferences, reviews   |
| Technical patterns + references | `memory_indexes/reference_*.md` | Patterns, conventions, APIs   |
| Specific technical issues       | Development history docs        | Detailed analysis + solutions |

### Step 3: Create/Update Entry

**If new**: Create file following template in `.update-memory.md`

**If existing**: Append/update facts while preserving structure

**Format**:

```markdown
- Fact type: specific detail with paths/commands
- Example: "Include path: lib/fcpp.hpp (verified at /fcpp_bridge/fcpp/src/lib/fcpp.hpp)"
```

### Step 4: Update Index in MEMORY.md

Add entry to `claude_code/MEMORY.md` index:

```markdown
- [Title](path/to/file.md) — one-line summary of key insight
```

### Step 5: Verify & Link

- Ensure all file paths are relative from `claude_code/`
- Verify links work
- Add cross-references to development_history docs if applicable
- Keep bullets and one-liners (no prose)

---

## Example Session: Transpiler Issue Discovery

**Session discoveries**:

- Include path fix (already documented)
- Transpiler code generation issues (5 root causes identified)
- Comprehensive refactor plan written

**MEMORY updates made**:

1. **Created**: `fcpp_bridge/development_history/TRANSPILER_CODEGEN_REFACTOR_PLAN.md`
   - Root causes, solutions, timeline, testing strategy

2. **Updated**: `claude_code/MEMORY.md` index
   - Added entry: `[Transpiler code generation issues](../development_history/TRANSPILER_CODEGEN_REFACTOR_PLAN.md) — missing node parameter, constants, types, namespace qualifications; refactor ~1 week`

3. **Updated**: `README.md`
   - Added "Known Limitations" section

4. **Updated**: `TUTORIAL_simple.md`, `TUTORIAL_in_depth.md`
   - Added transpiler limitations notes with workarounds

---

## Auto-Invocation Trigger Points

**Automatically update MEMORY when**:

- Major issue root cause identified
- Multi-file refactor plan created
- Environment setup process completed
- Build/run command sequence verified
- Testing pattern or strategy established
- Code review or user feedback processed

**Don't update for**:

- Trivial bug fixes
- Minor code reformatting
- One-off debugging sessions (unless finding is reusable)

---

## Quality Checklist

Before considering MEMORY update complete:

- [ ] Facts are specific (include paths, line numbers, commands)
- [ ] Links work (relative from claude_code/)
- [ ] Entries are added to MEMORY.md index
- [ ] No duplicate facts in existing entries
- [ ] Format consistent with existing files
- [ ] One-liners only (no detailed prose)
- [ ] File timestamp updated if modified
- [ ] Cross-references to other docs added

---

## Long-term Goal: Full Automation Agent

Future enhancement: Create a dedicated MCP server or VS Code extension that:

1. **Monitors** file changes and discoveries in real-time
2. **Proposes** MEMORY entries with diffs
3. **Batches** updates for review at session end
4. **Maintains** cross-references and consistency checks
5. **Exports** MEMORY as structured knowledge graphs

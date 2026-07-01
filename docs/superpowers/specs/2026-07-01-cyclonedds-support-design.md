# CycloneDDS Support — Design

**Date:** 2026-07-01
**Branch:** cyclone-dds
**Status:** Approved, ready for implementation planning

## Goal

The project currently optimizes **FastDDS** configuration for ROS2 applications
using an LLM-driven epoch loop. Add support for a second DDS implementation,
**CycloneDDS**, in the *same* codebase (not a fork), selected per-run.

In real ROS2 deployments a user runs exactly one DDS implementation at a time.
The two implementations share almost all of the optimization machinery; only
config generation, validation, deployment, and the parameter knowledge base
differ. A fork would force double-maintenance of the large shared core, so we
keep one codebase and introduce a thin vendor abstraction.

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Code structure | One codebase + `DDSBackend` abstraction | ~80% of code is vendor-agnostic; the FastDDS coupling is already isolated in `config/`. A fork would drift within weeks. |
| Vendor selection | `<dds_implementation>` field in `user_requirements.xml` | All info for a run lives in one reproducible file. Defaults to `fastdds` for backward compatibility. |
| CycloneDDS XML generation | Generic `xml_path`-driven generator | The CycloneDDS KB already carries an `xml_path` per parameter. A path-driven generator needs no code change when parameters are added. |
| FastDDS generator | **Keep** the existing hand-written generator | It works and encodes special constraints (e.g. SHM `segment_size >= maxMessageSize`). Migrating it adds risk for no benefit this iteration. |
| Package rename | `fastdds_optimizer` → `dds_optimizer` now | The tool is no longer FastDDS-only; name should reflect that. |
| Backward-compat alias | **None** | Confirmed with user — no `fastdds-optimizer` alias entry point. |

## Architecture

Introduce a `DDSBackend` abstraction. The shared core (optimizer loop,
benchmark, LLM client/protocol, dashboard, requirements, environment) is
unchanged in logic; it interacts with a backend object for the vendor-specific
steps: generate XML, validate, deploy (env var), and provide the KB path +
prompt wording.

```
src/dds_optimizer/                    (renamed from fastdds_optimizer)
├── backends/                         ← NEW
│   ├── base.py                       DDSBackend abstract base class (ABC)
│   ├── registry.py                   name → backend instance
│   ├── fastdds/
│   │   └── backend.py                wraps existing generator/validator/deployer
│   └── cyclonedds/
│       ├── backend.py
│       ├── generator.py              ← NEW: generic xml_path-driven generator
│       └── validator.py              ← NEW: CycloneDDS structure validator
├── config/                           existing FastDDS generator/validator/deployer
│                                     (retained; wrapped by fastdds backend)
├── optimizer/, llm/, benchmark/,     shared, near-unchanged
│   requirements/, environment/,
│   dashboard/, utils/, models.py
```

### `DDSBackend` interface

```python
class DDSBackend(ABC):
    name: str                     # "fastdds" | "cyclonedds"
    profiles_env_var: str         # FASTRTPS_DEFAULT_PROFILES_FILE | CYCLONEDDS_URI
    rmw_implementation: str       # rmw_fastrtps_cpp | rmw_cyclonedds_cpp

    def knowledge_base_path(self) -> Path         # this backend's performance_critical_params.json
    def prompt_expertise(self) -> str             # system-prompt opening line + format notes
    def generate_config(self, params: dict, out_path: Path) -> Path
    def validate_config(self, config_path: Path) -> list[str]
```

### Loop change (minimal)

In `optimization_loop.py`:
- At start: `backend = get_backend(requirements.dds_implementation)`.
- Epoch 1: still copies the user-provided `--initial-config` directly.
- Epoch 2+: `backend.generate_config(current_config_params, config_path)`
  instead of the hard-coded `generate_fastdds_config(...)`.

## CycloneDDS Generic Generator

The CycloneDDS KB gives each parameter an `xml_path`, e.g.:

```
"ack_delay":                  "CycloneDDS/Domain/Internal/AckDelay"                    (element text)
"socket_receive_buffer_size": "CycloneDDS/Domain/Internal/SocketReceiveBufferSize/@min" (attribute)
```

Generator mechanism:

1. **Sparse generation** — emit only the parameters the LLM actually `set`;
   everything else uses CycloneDDS defaults. CycloneDDS treats absent elements
   as "use default", so we do NOT fill the tree with defaults (unlike the
   FastDDS generator). Output is minimal and introduces no unintended behavior.

2. **Path-driven tree build** — for each param, look up its `xml_path` in the KB,
   split on `/`, and get-or-create each parent node (cached by path prefix to
   share parents, e.g. `Internal/AckDelay` and `Internal/NackDelay` share one
   `<Internal>`).

3. **`@attr` handling** — if the last segment starts with `@` (e.g.
   `.../SocketReceiveBufferSize/@min`), set that attribute on the second-to-last
   node; otherwise set the element's `.text`.

4. **`<Domain Id="any">`** — when creating the `Domain` node, add `Id="any"`
   (matches the reference `cyclonedds_config.xml`).

5. **Values passed through verbatim** — CycloneDDS natively accepts
   unit-suffixed strings (`"64 KiB"`, `"100 ms"`, `"512 kB"`), which is exactly
   how the KB `default` values are written. The LLM emits e.g.
   `"socket_receive_buffer_size": "8 MiB"` and the generator writes it as-is.
   No unit conversion.

Sketch:

```python
def generate(params: dict, kb: dict, out: Path):
    root = Element("CycloneDDS", xmlns="https://cdds.io/config")
    node_cache = {"CycloneDDS": root}
    for name, value in params.items():
        xml_path = kb["parameters"][name]["xml_path"]
        segments = xml_path.split("/")
        _apply_path(root, node_cache, segments, value)
    _write(root, out)
```

~80 lines covers all ~40 performance-critical parameters, and adding KB
parameters later requires no generator change.

### CycloneDDS validator

Lightweight: well-formed XML, root is `<CycloneDDS>`, at least one `<Domain>`.
Sparse generation already guarantees structural correctness.

## Knowledge Base Layout

```
data/knowledge_base/
├── fastdds/
│   ├── performance_critical_params.json   (moved from data/knowledge_base/)
│   └── fast_dds_complete_params.json
└── cyclonedds/
    └── performance_critical_params.json   (moved from cyclonedds-config-summary/)
```

Each backend's `knowledge_base_path()` points at its own file. The CycloneDDS
KB uses the *same schema* as FastDDS (name/type/default/range/impact/description),
so the existing prompt table rendering, response parsing, accumulated-params
tracking, and delete-revert logic all work unchanged.

`cyclonedds_complete_params.json` (currently has an empty `parameters` object and
a different top-level key) is NOT wired in this iteration — kept as reference only.

## Prompt Builder Changes (minimal)

`llm/prompt_builder.py` currently hard-codes the KB path and the
"expert in FastDDS" wording. Parameterize by backend:

- `_load_performance_critical_params()` reads from `backend.knowledge_base_path()`.
- System-prompt opening line comes from `backend.prompt_expertise()`.
- Table title `"Available FastDDS Parameters"` → `"Available {backend.name} Parameters"`.
- CycloneDDS backend injects one extra format note: values are unit-suffixed
  strings, e.g. `"8 MiB"`, `"100 ms"`.

`_format_params_reference`, `_normalize_params`, and the `{"set","delete"}`
protocol are reused unchanged.

## Vendor Selection Wiring

- `models.py`: `RequirementsConfig` gains `dds_implementation: str = "fastdds"`.
- `requirements/parser.py`: parse `<dds_implementation>` under the root; validate
  value ∈ {`fastdds`, `cyclonedds`}; default `fastdds` when absent.
- `optimization_loop.py`: resolve backend once at start; route all config
  generate/validate/deploy through it.
- `benchmark/launcher.py`: export `backend.profiles_env_var=<config>` **and**
  `RMW_IMPLEMENTATION=backend.rmw_implementation` for the benchmark subprocess.
  The RMW export is essential — without it CycloneDDS would not read the config.
- `config/deployer.py`: parameterize the env var name (currently hard-codes
  `FASTRTPS_DEFAULT_PROFILES_FILE`). CycloneDDS uses `CYCLONEDDS_URI`.

## Package Rename

`fastdds_optimizer` → `dds_optimizer`:

- `git mv src/fastdds_optimizer src/dds_optimizer` (preserve history).
- Replace all import paths (22 files reference `fastdds_optimizer`/relative imports).
- `pyproject.toml`: `[project.scripts]` `fastdds-optimizer` → `dds-optimizer`;
  wheel `packages` path; add `cyclonedds` to keywords.
- `main.py`: prog name, help text, `create_parser`; `cmd_run` success output
  prints the correct env-var export per backend (not hard-coded `FASTRTPS_...`).
- README, `example/`, `scripts/test_all_components.sh` command names.
- **No** backward-compat alias (confirmed with user).

## Testing Strategy

Existing `tests/unit/` (9 files, incl. `test_fastdds_generator.py`,
`test_config_generator.py`):

- After rename + import fix, run the full suite to confirm nothing broke.

New tests:

- `test_cyclonedds_generator.py`:
  - element vs `@attr` dispatch,
  - parent-node reuse (`Internal/AckDelay` + `Internal/NackDelay` share `<Internal>`),
  - unit-suffixed string pass-through,
  - `<Domain Id="any">` present,
  - sparse output (only `set` params appear).
- `test_cyclonedds_validator.py`.
- `test_backend_registry.py`: name→backend, unknown name errors, default fastdds.
- `test_requirements_parser` additions: `<dds_implementation>` parsing; default
  when absent.

Provide a CycloneDDS example initial config (reuse the reference
`cyclonedds_config.xml`).

## Out of Scope (YAGNI)

- Migrating the FastDDS generator to the generic path-driven approach.
- Wiring in `cyclonedds_complete_params.json`.
- A CLI `--dds` flag (selection is via XML field).
- Runtime auto-detection of the DDS vendor from `RMW_IMPLEMENTATION`.
- Backward-compatibility `fastdds-optimizer` alias.

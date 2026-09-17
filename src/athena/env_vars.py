"""Environment variable name constants for the Athena harness.

All env-var reads in the codebase use these constants instead of inline strings so that a
rename only requires changing this file. For values the process cannot run without, read them
via get_required() rather than os.environ.get() — it bombs on a missing var instead of
letting a None/"" default leak downstream.

Naming follows the prefix groups:
  ATHENA_        — harness core (model backends, any process)
  ATHENA_ENS_    — ensemble loader
  ATHENA_SRV_    — server and API layer
  ATHENA_UI_     — reserved for future frontend use
"""

import os

###############
# CONSTS / GLOBALS #
###############

# ATHENA_ — harness core
# NOTE: model backends read no shared credential vars here. Provider auth is per-backend:
#   - Anthropic: athena.model_backends.anthropic.API_KEY_ENV (ATHENA_ANTHROPIC_API_KEY)
#   - Ollama / OpenAI-compatible: NO global vars. Each ensemble element declares its own
#     `ollama_base_url` and `auth_headers_env` (header -> env var) in the manifest.

# ATHENA_ENS_ — ensemble
ENS_PATH             = "ATHENA_ENS_PATH"

# ATHENA_SRV_ — server and API
SRV_ORCHESTRATOR_MODEL    = "ATHENA_SRV_ORCHESTRATOR_MODEL"
SRV_ORCHESTRATOR_PROVIDER = "ATHENA_SRV_ORCHESTRATOR_PROVIDER"  # required: backend provider name
SRV_ORCHESTRATOR_CONFIG   = "ATHENA_SRV_ORCHESTRATOR_CONFIG"    # required: JSON object -> make_backend config ("{}" = none)
SRV_MAX_CONCURRENT_RUNS   = "ATHENA_SRV_MAX_CONCURRENT_RUNS"    # optional: max engagements executing at once (default 2)
SRV_PROJECTS_DIR          = "ATHENA_SRV_PROJECTS_DIR"           # optional: runtime project store root (default "workspace")
SRV_REPORT_CHAT_MODEL     = "ATHENA_SRV_REPORT_CHAT_MODEL"
SRV_REPORT_CHAT_PROVIDER  = "ATHENA_SRV_REPORT_CHAT_PROVIDER"
SRV_COLLABORATION_ENABLED = "ATHENA_SRV_COLLABORATION_ENABLED"
SRV_RESEND_API_KEY        = "ATHENA_SRV_RESEND_API_KEY"
SRV_RESEND_WEBHOOK_SECRET = "ATHENA_SRV_RESEND_WEBHOOK_SECRET"
SRV_COLLAB_REPLY_DOMAIN   = "ATHENA_SRV_COLLAB_REPLY_DOMAIN"
SRV_COLLABORATOR_ALIASES  = "ATHENA_SRV_COLLABORATOR_ALIASES"


###############
# FUNCTIONS #
###############

def get_required(env_var_name: str) -> str:
    """Read a required environment variable, raising ValueError if it is unset or blank.

    Use this instead of os.environ.get() for any config value the process cannot run without:
    it fails loudly at the point of use rather than defaulting to None/"" and failing later
    (or worse, silently). Only genuinely optional values (feature flags, opt-in config) should
    still use os.environ.get() with a default.
    """
    value = os.environ.get(env_var_name)
    if value is None or not value.strip():
        raise ValueError(f"Required environment variable '{env_var_name}' is not set")
    return value

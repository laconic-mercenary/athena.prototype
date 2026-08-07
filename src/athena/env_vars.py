"""Environment variable name constants for the Athena harness.

All os.environ.get() calls in the codebase use these constants instead of
inline strings so that a rename only requires changing this file.

Naming follows the prefix groups:
  ATHENA_        — harness core (model backends, any process)
  ATHENA_ENS_    — ensemble loader
  ATHENA_SRV_    — server and API layer
  ATHENA_UI_     — reserved for future frontend use
"""

###############
# CONSTS / GLOBALS #
###############

# ATHENA_ — harness core
ANTHROPIC_API_KEY    = "ATHENA_ANTHROPIC_API_KEY"
OLLAMA_API_KEY       = "ATHENA_OLLAMA_API_KEY"
OLLAMA_BASE_URL      = "ATHENA_OLLAMA_BASE_URL"

# ATHENA_ENS_ — ensemble
ENS_PATH             = "ATHENA_ENS_PATH"
ENS_DEFAULT_MODEL    = "ATHENA_ENS_DEFAULT_MODEL"
ENS_DEFAULT_PROVIDER = "ATHENA_ENS_DEFAULT_PROVIDER"

# ATHENA_SRV_ — server and API
SRV_ORCHESTRATOR_MODEL    = "ATHENA_SRV_ORCHESTRATOR_MODEL"
SRV_REPORT_CHAT_MODEL     = "ATHENA_SRV_REPORT_CHAT_MODEL"
SRV_REPORT_CHAT_PROVIDER  = "ATHENA_SRV_REPORT_CHAT_PROVIDER"
SRV_COLLABORATION_ENABLED = "ATHENA_SRV_COLLABORATION_ENABLED"
SRV_RESEND_API_KEY        = "ATHENA_SRV_RESEND_API_KEY"
SRV_RESEND_WEBHOOK_SECRET = "ATHENA_SRV_RESEND_WEBHOOK_SECRET"
SRV_COLLAB_REPLY_DOMAIN   = "ATHENA_SRV_COLLAB_REPLY_DOMAIN"
SRV_COLLABORATOR_ALIASES  = "ATHENA_SRV_COLLABORATOR_ALIASES"

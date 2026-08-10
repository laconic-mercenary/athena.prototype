"""API payload validation limits.

Every constant is documented with its rationale so reviewers know why the ceiling
is set at a particular value and can adjust it confidently when requirements change.
"""

###############
# CONSTS / GLOBALS #
###############

# Maximum length for operator chat messages sent to the orchestrator or a committee
# leader. 2 000 characters comfortably covers multi-sentence operator instructions
# without letting extremely long messages bloat the model's context window.
MAX_MESSAGE_LEN = 2000

# Maximum length for the operator's Redo suggestion or the text field of a gate
# decision. Mirrors MAX_MESSAGE_LEN — a concise redirection note is all that is
# needed here; richer instructions belong in a fresh engagement brief.
MAX_SUGGESTION_LEN = 2000

# Maximum length for the engagement's initial instructions. 8 192 characters allows
# rich multi-paragraph briefing text (typical red-team instruction sets run 1–3 KB)
# while rejecting accidental submission of unbounded copy-pastes or file dumps.
MAX_INSTRUCTIONS_LEN = 8192

# Maximum length for a specialist compound key ({committee}/{element_id}/{specialist_id}).
# 400 characters gives generous room for three dot-or-slash-separated path segments
# while preventing pathologically long keys from growing the in-memory disabled set.
MAX_KEY_LEN = 400

# Maximum length for an element or winner ID referenced in loop-gate requests.
# Ensemble-defined IDs are short slugs; 200 characters is well above that while
# still bounding the field against large-payload edge cases.
MAX_ID_LEN = 200

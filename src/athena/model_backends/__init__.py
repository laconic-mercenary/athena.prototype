"""Concrete ModelBackend implementations — one module per provider.

The shared interface (ModelBackend), the provider-neutral types (ToolDefinition,
ToolCall, ModelResponse), and the make_backend() factory live one level up in
athena.model_backend. Import a concrete backend from its own module, e.g.::

    from athena.model_backends.ollama import OllamaBackend

This package intentionally does NOT re-export the backends at package level, so
importing one provider never eagerly pulls in another provider's SDK.
"""

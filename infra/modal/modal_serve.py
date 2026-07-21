"""
Modal deployment — Foundation-Sec-8B-Reasoning (safetensors, vLLM)
Served via vLLM's OpenAI-compatible API on an A10G GPU.

vLLM is used instead of llama-cpp-python because it has native Llama 3.1
tool calling support via --tool-call-parser llama3_json, operating at the
tokenizer level rather than via chat format templates.

Setup (one time):
    modal secret create athena-vllm-key VLLM_API_KEY=<your-token>
    modal run infra/modal/modal_serve.py::download_model
    modal deploy infra/modal/modal_serve.py

Point athena.yml at the printed URL:
    model:
      ollama_base_url: https://<workspace>--athena-foundation-sec-serve.modal.run

Set locally before running Athena:
    export OLLAMA_API_KEY=<your-token>
"""

from __future__ import annotations

import os
import modal

MODEL_ID    = "fdtn-ai/Foundation-Sec-8B-Reasoning"
MODEL_DIR   = "/models/foundation-sec-8b"
SERVED_NAME = "foundation-sec-8b"
PORT        = 8000

app = modal.App("athena-foundation-sec")

model_volume = modal.Volume.from_name("athena-model-weights", create_if_missing=True)

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.1.1-devel-ubuntu22.04",
        add_python="3.11",
    )
    .pip_install("vllm>=0.7,<1", "huggingface_hub>=0.23", "hf-transfer>=0.1")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)


@app.function(
    image=image,
    volumes={"/models": model_volume},
    timeout=7200,
)
def download_model() -> None:
    """Download Foundation-Sec safetensors weights into the volume. Run once."""
    from pathlib import Path
    from huggingface_hub import snapshot_download

    dest = Path(MODEL_DIR)
    if dest.exists() and any(dest.iterdir()):
        print(f"Already cached: {MODEL_DIR}")
        return

    print(f"Downloading {MODEL_ID} → {MODEL_DIR} …")
    snapshot_download(repo_id=MODEL_ID, local_dir=MODEL_DIR)
    model_volume.commit()
    print("Done.")


@app.function(
    image=image,
    gpu="A10G",
    memory=32768,
    volumes={"/models": model_volume},
    secrets=[modal.Secret.from_name("athena-vllm-key")],
    # Keep one container warm so the Signal Analyst never pays an 8B cold-start
    # (container spin-up + weight load) on the first request. Costs a continuously
    # running A10G — set back to 0 outside demo/active-use windows to save spend.
    min_containers=1,
    scaledown_window=300,
    timeout=3600,
)
@modal.concurrent(max_inputs=4)
@modal.web_server(port=PORT, startup_timeout=300)
def serve() -> None:
    """Start vLLM with Llama 3.1 tool calling enabled."""
    import subprocess

    api_key = os.environ.get("VLLM_API_KEY", "")
    cmd = [
        "python", "-m", "vllm.entrypoints.openai.api_server",
        "--model", MODEL_DIR,
        "--served-model-name", SERVED_NAME,
        "--host", "0.0.0.0",
        "--port", str(PORT),
        "--max-model-len", "32768",
        "--dtype", "bfloat16",
        "--enable-auto-tool-choice",
        "--tool-call-parser", "llama3_json",
        "--safetensors-load-strategy", "prefetch",
    ]
    if api_key:
        cmd += ["--api-key", api_key]

    print("Starting vLLM:", " ".join(cmd))
    subprocess.Popen(cmd)

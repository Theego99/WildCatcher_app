"""WildCatcher GPU/compute device utilities."""
import platform
import torch


def get_best_device():
    """Select the best available compute device: CUDA > MPS > CPU."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def get_gpu_diagnostics():
    """Return a list of diagnostic strings about the compute environment."""
    lines = []
    lines.append("=" * 50)
    lines.append("COMPUTE DEVICE DIAGNOSTICS")
    lines.append("=" * 50)

    torch_ver = torch.__version__
    lines.append(f"PyTorch version: {torch_ver}")
    lines.append(f"Platform: {platform.system()} {platform.machine()}")
    is_cpu_build = "+cpu" in torch_ver

    # CUDA
    lines.append(f"CUDA available: {torch.cuda.is_available()}")
    cuda_works = False
    if torch.cuda.is_available():
        lines.append(f"CUDA version: {torch.version.cuda}")
        for i in range(torch.cuda.device_count()):
            name = torch.cuda.get_device_name(i)
            mem = torch.cuda.get_device_properties(i).total_memory / (1024 ** 3)
            cap = torch.cuda.get_device_capability(i)
            lines.append(f"  GPU {i}: {name} ({mem:.1f} GB, sm_{cap[0]}{cap[1]})")
        # Validate GPU actually works (catches architecture mismatches)
        try:
            _t = torch.zeros(1, device="cuda")
            _ = _t + 1
            del _t
            cuda_works = True
            lines.append("STATUS: Using NVIDIA GPU (CUDA)")
        except RuntimeError as e:
            lines.append(f"CUDA validation FAILED: {e}")
            lines.append("STATUS: GPU detected but incompatible — will fall back to CPU.")

    # MPS (Apple Silicon)
    mps_available = False
    try:
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            mps_available = True
    except Exception:
        pass
    lines.append(f"MPS (Apple Silicon) available: {mps_available}")
    if mps_available and not torch.cuda.is_available():
        lines.append("STATUS: Using Apple GPU (MPS)")

    # CPU fallback
    if not torch.cuda.is_available() and not mps_available:
        lines.append("WARNING: No GPU acceleration — running on CPU only.")
        if is_cpu_build:
            lines.append("REASON: PyTorch is a CPU-only build (version contains '+cpu').")
            lines.append("FIX: pip uninstall torch torchvision && pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121")
        elif platform.system() == "Darwin":
            lines.append("NOTE: On macOS Intel, CPU-only is expected. Apple Silicon (M1+) should show MPS.")
        else:
            lines.append("Possible causes: no NVIDIA GPU, missing drivers (run nvidia-smi), or CUDA mismatch.")
        lines.append("Processing will work but will be SLOWER without GPU.")

    lines.append(f"Selected device: {get_best_device()}")
    lines.append("=" * 50)
    return lines

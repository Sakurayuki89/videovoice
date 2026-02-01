import torch
import gc


def clear_vram(component_name: str = "System"):
    """Clear VRAM and run garbage collection. Works on both CUDA and CPU."""
    print(f"\n[{component_name}] Clearing memory...")

    # Always run garbage collection
    gc.collect()

    # Only perform CUDA operations if available
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()  # Ensure all CUDA operations are complete
        print(f"VRAM Allocated: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")
        print(f"VRAM Reserved:  {torch.cuda.memory_reserved() / 1024**3:.2f} GB")
    else:
        print("Running on CPU - no VRAM to clear")


def get_device() -> str:
    """Get the best available device (cuda or cpu)."""
    return "cuda" if torch.cuda.is_available() else "cpu"


def get_vram_info() -> dict:
    """Get VRAM usage information."""
    if not torch.cuda.is_available():
        return {"available": False, "device": "cpu"}

    return {
        "available": True,
        "device": torch.cuda.get_device_name(0),
        "total_gb": torch.cuda.get_device_properties(0).total_memory / 1024**3,
        "allocated_gb": torch.cuda.memory_allocated() / 1024**3,
        "reserved_gb": torch.cuda.memory_reserved() / 1024**3,
    }

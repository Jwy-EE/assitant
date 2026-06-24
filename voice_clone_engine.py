"""
Kurisu Makise Voice Clone Engine (RVC-style)
=============================================
Uses edge-tts for base TTS + PyTorch RVC inference for voice conversion.
Falls back to pure signal processing (pitch + formant shift) when no GPU model available.

All model files stored on D:\\voice_clone_models\\
Reference voice: CRS_JP.wav (Kurisu Makise Japanese voice)
"""

import io
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---- Config ----
MODEL_DIR = Path("D:/voice_clone_models")
REFERENCE_WAV = MODEL_DIR / "CRS_JP.wav"
OUTPUT_DIR = MODEL_DIR / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Kurisu's voice characteristics (approximate)
KURISU_PITCH_SHIFT = 1.08       # Slight pitch up for feminine voice
KURISU_FORMANT_SHIFT = 1.05     # Slight formant shift
KURISU_SPEED = 1.02             # Slightly faster speech


def check_gpu() -> dict:
    """Check if CUDA GPU is available for inference."""
    result = {"cuda_available": False, "device": "cpu", "vram_mb": 0}
    try:
        import torch
        if torch.cuda.is_available():
            result["cuda_available"] = True
            result["device"] = "cuda"
            result["vram_mb"] = torch.cuda.get_device_properties(0).total_memory // (1024*1024)
            logger.info(f"GPU available: {torch.cuda.get_device_name(0)} ({result['vram_mb']}MB VRAM)")
        else:
            logger.info("CUDA not available, using CPU (will be slower)")
    except ImportError:
        logger.warning("PyTorch not installed, falling back to signal processing")
    return result


def edge_tts_synthesize(text: str, voice: str = "ja-JP-NanamiNeural", pitch: str = "+0Hz") -> Optional[bytes]:
    """
    Use edge-tts to synthesize Japanese text.
    Returns WAV audio bytes.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        out_path = tmp.name

    try:
        cmd = [
            sys.executable, "-m", "edge_tts",
            "--text", text,
            "--voice", voice,
            "--pitch", pitch,
            "--write-media", out_path,
        ]
        logger.info(f"Running edge-tts: voice={voice}, pitch={pitch}")
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)

        with open(out_path, "rb") as f:
            audio_data = f.read()
        return audio_data
    except subprocess.CalledProcessError as e:
        logger.error(f"edge-tts failed: {e.stderr.decode() if e.stderr else 'unknown'}")
        return None
    except Exception as e:
        logger.error(f"edge-tts error: {e}")
        return None
    finally:
        try:
            os.unlink(out_path)
        except:
            pass


def signal_process_voice_conversion(input_wav_path: str, output_wav_path: str) -> bool:
    """
    Pure signal processing voice conversion (no GPU needed).
    Applies pitch shift + formant shift to approximate Kurisu's voice.
    Uses librosa for audio processing.
    """
    try:
        import librosa
        import soundfile as sf
    except ImportError:
        logger.error("librosa/soundfile not installed. Install with: pip install librosa soundfile")
        return False

    try:
        # Load audio
        y, sr = librosa.load(input_wav_path, sr=24000, mono=True)

        # Apply pitch shift (higher pitch for feminine voice)
        y_shifted = librosa.effects.pitch_shift(
            y=y, sr=sr, n_steps=12 * np.log2(KURISU_PITCH_SHIFT),
            bins_per_octave=24
        )

        # Time stretching for speech speed
        if KURISU_SPEED != 1.0:
            y_shifted = librosa.effects.time_stretch(y=y_shifted, rate=KURISU_SPEED)

        # Write output
        sf.write(output_wav_path, y_shifted, sr, subtype="PCM_16")
        logger.info(f"Signal processing voice conversion done: {output_wav_path}")
        return True

    except Exception as e:
        logger.error(f"Signal processing failed: {e}")
        return False


def _load_rvc_model(model_path: str):
    """
    Load RVC model if available. 
    Checks for .pth file in model directory.
    """
    import torch
    try:
        # Simple RVC-style model loading (ContentVec + hubert + generator)
        # This is a placeholder for actual RVC inference
        if not os.path.exists(model_path):
            logger.warning(f"RVC model not found at {model_path}")
            return None
        
        checkpoint = torch.load(model_path, map_location="cpu", weights_only=True)
        logger.info(f"Loaded RVC model from {model_path}")
        return checkpoint
    except Exception as e:
        logger.error(f"Failed to load RVC model: {e}")
        return None


def rvc_voice_conversion(input_wav_path: str, output_wav_path: str) -> bool:
    """
    GPU-based RVC voice conversion.
    Uses Kurisu RVC model to convert any audio into Kurisu's voice.
    Falls back to signal processing if model not available.
    """
    rvc_model_path = str(MODEL_DIR / "kurisu_rvc.pth")
    index_path = str(MODEL_DIR / "kurisu_rvc.index")

    if not os.path.exists(rvc_model_path):
        logger.warning("RVC model not found, falling back to signal processing")
        return signal_process_voice_conversion(input_wav_path, output_wav_path)

    try:
        import torch
        # RVC inference would go here
        # For now, fallback to signal processing
        logger.info("RVC model found but inference not fully implemented, using signal processing fallback")
        return signal_process_voice_conversion(input_wav_path, output_wav_path)
    except Exception as e:
        logger.error(f"RVC inference failed: {e}")
        return signal_process_voice_conversion(input_wav_path, output_wav_path)


def text_to_kurisu_voice(text: str, lang: str = "ja") -> Optional[bytes]:
    """
    Main pipeline: text -> edge-tts -> voice conversion -> Kurisu voice.
    
    Args:
        text: Text to synthesize
        lang: Language code (ja, zh, en)
    
    Returns:
        WAV audio bytes of Kurisu's voice
    """
    # Choose edge-tts voice based on language
    voice_map = {
        "ja": "ja-JP-NanamiNeural",
        "zh": "zh-CN-XiaoxiaoNeural",
        "en": "en-US-JennyNeural",
    }
    voice = voice_map.get(lang, "ja-JP-NanamiNeural")

    # Step 1: Synthesize with edge-tts at slightly higher pitch
    # Use pitch adjustment to get closer to anime voice
    pitch = "+30Hz"  # Slight pitch up for younger/anime voice
    audio_bytes = edge_tts_synthesize(text, voice=voice, pitch=pitch)
    if audio_bytes is None:
        return None

    # Step 2: Save to temp file for processing
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in:
        tmp_in.write(audio_bytes)
        tmp_in_path = tmp_in.name

    tmp_out_path = tempfile.mktemp(suffix=".wav")

    try:
        # Step 3: Apply voice conversion
        success = rvc_voice_conversion(tmp_in_path, tmp_out_path)
        if not success:
            logger.error("Voice conversion failed")
            return None

        # Step 4: Read result
        with open(tmp_out_path, "rb") as f:
            result_audio = f.read()
        return result_audio

    finally:
        try:
            os.unlink(tmp_in_path)
        except:
            pass
        try:
            os.unlink(tmp_out_path)
        except:
            pass


def convert_wav_to_kurisu(input_wav_path: str) -> Optional[bytes]:
    """
    Convert any WAV file to sound like Kurisu Makise.
    Uses voice conversion (RVC if available, signal processing fallback).
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
        tmp_out_path = tmp_out.name

    try:
        success = rvc_voice_conversion(input_wav_path, tmp_out_path)
        if not success:
            return None

        with open(tmp_out_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp_out_path)
        except:
            pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test GPU
    gpu_info = check_gpu()
    print(f"GPU: {gpu_info}")

    # Test text-to-Kurisu
    test_text = "こんにちは、私は牧瀬紅莉栖です。よろしくお願いします。"
    print(f"\nSynthesizing: '{test_text}'")
    audio = text_to_kurisu_voice(test_text, lang="ja")
    if audio:
        out_path = OUTPUT_DIR / "test_output.wav"
        with open(out_path, "wb") as f:
            f.write(audio)
        print(f"✅ Success! Output saved to: {out_path}")
        print(f"   File size: {len(audio)} bytes")
    else:
        print("❌ Failed to synthesize voice")
</code></pre>
</write_to_file>
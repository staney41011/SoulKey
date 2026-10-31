"""Real English Edge CPU smoke through formal audio assembly, with synthetic text."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tts_runner import render_natural_language

SAMPLES = [
    {"id": 1, "start": 0, "end": 9,
     "text": "Learning with patience and care helps us appreciate the people around us. Each small action of kindness can make a meaningful difference."},
    {"id": 2, "start": 9, "end": 17,
     "text": "Taking a little time for thoughtful reflection allows us to make better choices and deepen our understanding of one another."},
]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    os.environ["SOULKEY_TTS_PARALLEL_BLOCKS"] = "2"
    dest = Path(args.output_dir)
    results = []
    for trial in range(2):
        result = render_natural_language(
            # Real spoken text runs ~17 s; an artificial 120 s source
            # should rightly need review after enforcing the 96% minimum.
            # Use a realistic source window to exercise formal MP3 output.
            SAMPLES, "en", dest, source_duration=19.0,
            duration_limit_basis="synthetic_integration_test",
        )
        manifest = json.loads(result["manifest"].read_text(encoding="utf-8"))
        assert result["status"] == "done", manifest.get("timeline")
        assert result["mp3"].stat().st_size > 1024
        assert result["wav"].stat().st_size > 1024
        assert manifest["source_sha256"]
        assert manifest["audio_receipts"]["mp3"]["size"] == result["mp3"].stat().st_size
        results.append({
            "trial": trial + 1,
            "blocks": len(manifest["blocks"]),
            "reused": sum(1 for x in manifest["blocks"] if x.get("reused")),
            "status": result["status"],
            "duration_s": manifest["timeline"]["final_duration"],
        })
    assert results[0]["reused"] == 0
    assert results[1]["reused"] == results[1]["blocks"]
    print("FULL_EDGE_CPU_SMOKE_PASSED", json.dumps(results), flush=True)

if __name__ == "__main__":
    main()

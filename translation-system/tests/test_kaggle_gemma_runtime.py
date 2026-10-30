"""Run real workflow metadata generation with a stale pulled Kaggle image."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"translation-system"))
import p259_gemma4_kaggle as gemma

class KaggleRuntimeTests(unittest.TestCase):
    def metadata(self,stage,task="P259-L01",langs="",lang="central4"):
        workflow=(ROOT/".github/workflows/kaggle_web_job.yml").read_text()
        step=workflow.split("      - name: Build formal SoulKey job",1)[1]
        source=textwrap.dedent(step.split("          python - <<'PY'\n",1)[1].split("\n          PY",1)[0])
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)/"soulkey-web-worker"
            folder.mkdir()
            metadata=folder/"kernel-metadata.json"
            metadata.write_text(json.dumps({"id_no":123,"docker_image":"old-image@sha256:stale",
                "docker_image_pinning_type":"original"}))
            environ={"RUNNER_TEMP":temporary,"JOB_TASK_ID":task,"JOB_STAGE":stage,
                "JOB_LANG":lang,"JOB_LANGS":langs,"JOB_RUNTIME_NONCE":"test-only-nonce",
                "JOB_BRIDGE_URL":"https://script.google.com/macros/s/test-only/exec"}
            with patch.dict(os.environ,environ),contextlib.redirect_stdout(io.StringIO()):
                exec(compile(source,"workflow-job-generator","exec"),{})
            generated=json.loads(metadata.read_text())
            worker=(folder/generated["code_file"]).read_text()
            compile(worker,"generated-private-worker","exec")
            return generated

    def test_gemma_removes_stale_digest_and_requests_supported_latest_image(self):
        for stage,langs in [("multi",""),("finish","ja,ko")]:
            with self.subTest(stage=stage):
                metadata=self.metadata(stage,langs=langs)
                self.assertNotIn("docker_image",metadata)
                self.assertEqual(metadata["docker_image_pinning_type"],"latest")
                self.assertTrue(metadata["enable_gpu"])
                self.assertTrue(metadata["is_private"])
                self.assertEqual(metadata["id"],"cwlmrcsir/soulkey-gpu-worker")
                self.assertEqual(metadata["kernel_sources"],["cwlmrcsir/translate-system"])
                self.assertEqual(metadata["model_sources"],[])
                self.assertNotIn("id_no",metadata)

    def test_other_jobs_do_not_silently_change_their_pulled_image(self):
        for stage,task in [("zh","P259-L01"),("tts","P259-L01"),("multi","P260-L01")]:
            with self.subTest(stage=stage,task=task):
                metadata=self.metadata(stage,task)
                self.assertEqual(metadata["docker_image"],"old-image@sha256:stale")
                self.assertEqual(metadata["docker_image_pinning_type"],"original")

    def test_binary_abi_is_checked_with_bounded_probe(self):
        result=subprocess.CompletedProcess([],0,stdout="llama.cpp b11988",stderr="")
        with patch("subprocess.run",return_value=result) as run,contextlib.redirect_stdout(io.StringIO()):
            env=gemma.verify_server_runtime(Path("/native/llama-server"),Path("/native"))
        self.assertEqual(run.call_args.args[0],["/native/llama-server","--version"])
        self.assertEqual(run.call_args.kwargs["timeout"],30)
        self.assertTrue(env["LD_LIBRARY_PATH"].startswith("/native"+os.pathsep))

    def test_old_glibc_image_fails_before_model_loading(self):
        result=subprocess.CompletedProcess([],1,stdout="",stderr="GLIBC_2.38 not found")
        with patch("subprocess.run",return_value=result),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,"docker_image_pinning_type=latest"):
                gemma.verify_server_runtime(Path("/native/llama-server"),Path("/native"))

if __name__=="__main__":unittest.main(verbosity=2)

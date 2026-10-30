import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
TREE=ast.parse((ROOT/"cloud-bridge/p259_gemma4_relay.py").read_text())


class ContinuationTests(unittest.TestCase):
    def test_generated_kernel_compiles_without_credentials(self):
        node=next(x for x in TREE.body if isinstance(x,ast.Assign)
                  and any(isinstance(t,ast.Name) and t.id=="KAGGLE_PY" for t in x.targets))
        code=ast.literal_eval(node.value).replace("__JOB_BASE64__",repr("e30="))
        compile(code,"private-kaggle-worker","exec")
        self.assertNotIn("GOOGLE_ACCESS_TOKEN",code)
        self.assertIn('Gemma(glossary=job.get("glossary",""))',code)

    def test_empty_queue_stops_chain_and_work_permits_continuation(self):
        main=next(x for x in TREE.body if isinstance(x,ast.FunctionDef) and x.name=="main")
        helper=main.body[0]
        scope={"os":os}
        exec(compile(ast.Module(body=[helper],type_ignores=[]),"continuation","exec"),scope)
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/"github-output"
            with patch.dict(os.environ,{"GITHUB_OUTPUT":str(output)}):
                scope["continuation"](False)
                scope["continuation"](True)
            self.assertEqual(output.read_text().splitlines(),["has_job=false","has_job=true"])

    def test_dispatch_has_hard_bound_and_does_not_repeat_empty_queue(self):
        text=(ROOT/".github/workflows/soulkey_translation_queue.yml").read_text()
        self.assertIn("steps.relay.outputs.has_job == 'true'",text)
        self.assertIn("inputs.remaining_runs > 0",text)
        self.assertIn('[[ "$REMAINING" -le 20 ]]',text)
        self.assertIn("NEXT=$((REMAINING - 1))",text)


if __name__=="__main__":unittest.main()

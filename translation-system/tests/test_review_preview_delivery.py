"""Only verified standalone review MP3 may be uploaded; no forged official MP3."""
import ast
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def function(rel,name,ns):
    filename=ROOT/rel
    tree=ast.parse(filename.read_text(encoding="utf8"))
    match=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name==name]
    assert len(match)==1
    exec(compile(ast.Module(body=match,type_ignores=[]),str(filename),"exec"),ns)
    return ns[name]

class ReviewPreviewUpload(unittest.TestCase):
    def test_smart_review_uploads_preview_before_manifest_without_formal_mp3(self):
        uploads=[]
        def upload(drive,folder,local_path,canonical_name,display_name=""):
            uploads.append((canonical_name,display_name))
            return {"id":"fake-existing-id"}
        ns={"Path":Path,"upload_or_replace_file":upload,
            "formal_drive_name":lambda task,n:"formal-"+n}
        uploader=function("translation-system/tts_runner.py","upload_natural_outputs",ns)
        with tempfile.TemporaryDirectory() as directory:
            names={
                "preview_mp3":"es.preview.mp3",
                "alignment_report":"es.alignment_report.json",
                "manifest":"es.tts_manifest.json",
                "narration_script":"es.narration_script.json",
                "smart_fit_report":"es.smart_fit_report.json",
            }
            result={"status":"needs_review",
                    **{key:Path(directory)/value for key,value in names.items()}}
            for path in result.values():
                if isinstance(path,Path):path.write_bytes(b"synthetic preview/report")
            uploader(object(),"fake-drive-folder",result,{"task_id":"P258-L03"})
        actual=[x[0] for x in uploads]
        self.assertEqual(actual,[
            "es.preview.mp3","es.narration_script.json",
            "es.smart_fit_report.json","es.alignment_report.json",
            "es.tts_manifest.json"])
        self.assertNotIn("es.mp3",actual)
        self.assertTrue(all(x[1].startswith("formal-") for x in uploads))

    def test_review_status_requires_drive_md5_receipt(self):
        code=(ROOT/"translation-system/tts_runner.py").read_text(encoding="utf8")
        self.assertIn('if status=="needs_review":',code)
        self.assertIn('f"{lang}.preview.mp3"',code)
        self.assertIn('local_audio_receipt(preview_mp3)',code)
        self.assertIn('delivered=verify_uploaded_natural_output(',code)
        self.assertIn('if delivered != result["status"]:',code)
        self.assertIn('timeline_mp3.unlink(missing_ok=True)',code)

if __name__=="__main__":
    unittest.main()

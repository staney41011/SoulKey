import hashlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from central_final_sync import central_final
from legacy_final_import import newer_legacy_final,publish_legacy_final

TASK="P259-L03"
OLD="2026-10-29T08:24:43Z"
NEW="2026-10-30T18:00:00Z"
SEGMENTS=[{"id":7,"start":0,"end":12,"text":"Original approved human text"}]


class FakeSheets:
    def __init__(self):
        text=json.dumps({"task_id":TASK,"kind":"en","segments":SEGMENTS})
        self.revision=hashlib.sha256(text.encode()).hexdigest()
        self.rows={"英文定稿索引":[[TASK,self.revision,"1",OLD,"google-sheet","previous"]],
          "英文定稿備存":[[TASK,self.revision,"0","1",text,OLD,self.revision]]}
        self.appends=[]
    def read(self,area):
        tab,span=area.replace("'","").split("!")
        import re
        numbers=[int(x) for x in re.findall(r"\d+",span)]
        first=numbers[0] if numbers else 2
        last=numbers[-1] if numbers else 15000
        return self.rows[tab][max(0,first-2):last-1]
    def spreadsheets(self):return self
    def values(self):return self
    def append(self,**args):
        tab=args["range"].replace("'","").split("!")[0]
        start=len(self.rows[tab])+2
        rows=args["body"]["values"]
        self.rows[tab].extend(rows)
        self.appends.append((tab,rows))
        result={"updates":{"updatedRange":tab+"!A"+str(start)+":G"+str(start+len(rows)-1)}}
        return types.SimpleNamespace(execute=lambda **kw:result)


class LegacyFinalTests(unittest.TestCase):
    def prior(self,sheets):
        return central_final(TASK,"en",sheets.rows["英文定稿索引"],sheets.rows["英文定稿備存"])
    def candidate(self,sheets):
        return newer_legacy_final(TASK,"en",{"finalized_at":NEW,
          "segments":[{**SEGMENTS[0],"text":"A new human correction"}]},self.prior(sheets))
    def publish(self,sheets,unchanged=lambda:True):
        io=types.SimpleNamespace(read_values=lambda s,_id,area:s.read(area))
        with patch.dict(sys.modules,{"google_io":io,"config":types.SimpleNamespace(SPREADSHEET_ID="control")}):
            return publish_legacy_final(TASK,"en",self.candidate(sheets),self.prior(sheets),sheets,unchanged)
    def test_newer_drive_final_updates_source_hash_and_retains_original_backups(self):
        sheets=FakeSheets();old_revision=sheets.revision
        final=self.publish(sheets)
        self.assertNotEqual(final["central_revision"],old_revision)
        self.assertEqual(final["segments"][0]["text"],"A new human correction")
        self.assertEqual(final["source"],"legacy-human-final")
        self.assertEqual(len(sheets.rows["英文定稿索引"]),2)
        self.assertEqual(sheets.rows["英文定稿備存"][0][1],old_revision)
        self.assertEqual(sheets.appends[-1][0],"英文定稿索引")
    def test_drive_changes_abort_before_canonical_index_commit(self):
        sheets=FakeSheets()
        with self.assertRaisesRegex(RuntimeError,"drive_final_changed"):
            self.publish(sheets,lambda:False)
        self.assertEqual(len(sheets.rows["英文定稿索引"]),1)
        self.assertEqual(len(sheets.rows["英文定稿備存"]),2)
    def test_older_drive_final_and_undated_sync_copy_do_not_replace_current_sheet(self):
        sheets=FakeSheets();prior=self.prior(sheets)
        self.assertIsNone(newer_legacy_final(TASK,"en",{"finalized_at":"2026-10-28T12:00:00Z"},prior))
        self.assertIsNone(newer_legacy_final(TASK,"en",{},prior))
    def test_unknown_or_equal_time_different_content_requires_review(self):
        prior=self.prior(FakeSheets())
        for stamp in ["2026-10-30 12:00:00",OLD]:
            with self.assertRaises(RuntimeError):newer_legacy_final(TASK,"en",{"finalized_at":stamp},prior)
    def test_wrong_task_or_duplicate_ids_never_publish(self):
        prior=self.prior(FakeSheets())
        with self.assertRaisesRegex(RuntimeError,"identity_mismatch"):
            newer_legacy_final(TASK,"en",{"task_id":"P259-L01","finalized_at":NEW},prior)
        with self.assertRaisesRegex(RuntimeError,"duplicate_source_segment_id"):
            newer_legacy_final(TASK,"en",{"finalized_at":NEW,"segments":SEGMENTS*2},prior)


if __name__=="__main__":unittest.main()

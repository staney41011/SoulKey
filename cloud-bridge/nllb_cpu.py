"""Offline, non-commercial multilingual translation fallback for SoulKey.

Uses the INT8-converted NLLB 600M model on GitHub Actions CPU.
License (original Meta model): CC BY-NC 4.0. Appropriate only when the
course and deployment are non-commercial; outputs require human review.
"""
import os
import re

NLLB={
 "th":"tha_Thai","es":"spa_Latn","id":"ind_Latn",
 "vi":"vie_Latn","km":"khm_Khmr","hi":"hin_Deva",
 "ta":"tam_Taml","ja":"jpn_Jpan","ko":"kor_Hang",
 "bn":"ben_Beng","ne":"npi_Deva","lo":"lao_Laoo",
 "my":"mya_Mymr","it":"ita_Latn","pt":"por_Latn"
}
class NllbCPU:
    def __init__(self):
        import ctranslate2
        import sentencepiece as spm
        from huggingface_hub import snapshot_download
        model=os.environ.get("SOULKEY_NLLB_REPO","osa911/nllb-200-distilled-600M-ct2-int8")
        root=snapshot_download(repo_id=model,allow_patterns=[
            "*.bin","*.json","*.model","*.txt"
        ])
        tokenizer=os.path.join(root,"sentencepiece.bpe.model")
        if not os.path.isfile(tokenizer):
            raise RuntimeError("NLLB sentencepiece tokenizer is missing")
        self.sp=spm.SentencePieceProcessor(model_file=tokenizer)
        self.model=ctranslate2.Translator(root,device="cpu",
           compute_type="int8",inter_threads=2,intra_threads=2)
        print("NLLB CPU offline translator loaded; results require review",flush=True)

    def split(self,text,limit=170):
        """Partition long paragraphs without deleting or truncating text."""
        words=re.findall(r"\S+\s*",text)
        parts=[];current=[]
        for word in words:
            trial="".join(current)+word
            if current and len(self.sp.encode_as_pieces(trial))>limit:
                parts.append("".join(current).strip())
                current=[word]
            else:
                current.append(word)
            if len(self.sp.encode_as_pieces(word))>limit:
                raise RuntimeError("A token could not be split into NLLB chunks")
        if current:parts.append("".join(current).strip())
        return parts

    def translate(self,language,segments):
        tgt=NLLB[language]
        flat=[];parent=[]
        for item in segments:
            chunks=self.split(str(item["text"]))
            for chunk in chunks:
                flat.append(chunk)
                parent.append(item["id"])
        translations=[]
        for start in range(0,len(flat),8):
            batch=flat[start:start+8]
            sources=[["eng_Latn"]+self.sp.encode_as_pieces(x)+["</s>"] for x in batch]
            result=self.model.translate_batch(
              sources,target_prefix=[[tgt]]*len(sources),
              beam_size=2,max_decoding_length=512,
              batch_type="tokens",max_batch_size=8
            )
            for candidate in result:
                tokens=list(candidate.hypotheses[0])
                if tokens and tokens[0]==tgt:tokens=tokens[1:]
                translated=self.sp.decode(tokens).strip()
                if not translated:raise RuntimeError("NLLB returned an empty translation")
                translations.append(translated)
            print("NLLB",language,len(translations),"/",len(flat),flush=True)
        assembled={item["id"]:[] for item in segments}
        for sid,translated in zip(parent,translations):
            assembled[sid].append(translated)
        return [{"id":item["id"],"text":" ".join(assembled[item["id"]])}
                for item in segments]

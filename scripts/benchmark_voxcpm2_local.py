#!/usr/bin/env python3
"""CPU-only local VoxCPM2 voice-design benchmark; no hosted TTS API."""
from __future__ import annotations
import argparse, csv, gc, hashlib, importlib.metadata, importlib.util
import json, os, platform, resource, shutil, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/"backend") not in sys.path: sys.path.insert(0,str(ROOT/"backend"))
MODEL_ID="openbmb/VoxCPM2"
MODEL_LICENSE="Apache-2.0"
PACKAGE_VERSION="2.0.3"
SAMPLE_RATE=48000
CFG_VALUE=2.0
INFERENCE_TIMESTEPS=10
IDENTITIES=(
 {"id":"voxcpm2-warm-female-01","label":"Warm clear female narrator","seed":20261102,
  "description":"A fictional adult female narrator with a warm medium-pitched voice, clear articulation, gentle confidence, natural pacing, soft vocal texture and expressive but restrained delivery. Designed to speak naturally in both Vietnamese and English."},
 {"id":"voxcpm2-resonant-male-01","label":"Resonant composed male narrator","seed":20261103,
  "description":"A fictional adult male narrator with a balanced medium-low pitch, rounded resonance, calm authority, crisp consonants, smooth phrasing and conversational warmth. Designed to speak naturally in both Vietnamese and English."},
)
UTTERANCES={
 "vi":(
  "Xin chào, hôm nay chúng ta sẽ khám phá một câu chuyện thú vị. Lúc 7 giờ 45 phút, nhóm nghiên cứu ghi nhận khoảng cách 12,6 ki-lô-mét.",
  "Điều quan trọng không chỉ nằm ở kết quả, mà còn ở cách chúng ta kiên nhẫn tìm hiểu từng chi tiết và kiểm chứng mọi thông tin.",
 ),
 "en":(
  "Hello, and welcome. Today we are exploring a fascinating story. At 7:45, the research team recorded a distance of 12.6 kilometres.",
  "What matters is not only the final result, but also the care we take to understand every detail and verify what we have learned.",
 ),
}

def validate_contract():
 if set(UTTERANCES)!={"en","vi"}: raise ValueError("Only EN and VI are in scope.")
 ids=[x["id"] for x in IDENTITIES]
 seeds=[x["seed"] for x in IDENTITIES]
 if len(ids)!=len(set(ids)) or len(seeds)!=len(set(seeds)) or any(not x["description"] for x in IDENTITIES): raise ValueError("Identity IDs, seeds and prompts must be unique/non-empty.")
 if len(IDENTITIES)!=2 or any(len(v)!=2 for v in UTTERANCES.values()): raise ValueError("Expected two identities and two texts per language.")

def load_builder():
 path=ROOT/"scripts"/"build_voice_library.py"
 spec=importlib.util.spec_from_file_location("voxcpm2_voice_library_builder",path)
 if not spec or not spec.loader: raise RuntimeError("Cannot load VoiceStudio audio validation helpers.")
 mod=importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod; spec.loader.exec_module(mod)
 return mod

def digest(path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for part in iter(lambda:f.read(1024*1024),b""): h.update(part)
 return h.hexdigest()

def rss_mib(): return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,1)

def memory_mib():
 try:
  for line in Path("/proc/meminfo").read_text().splitlines():
   if line.startswith("MemTotal:"): return round(int(line.split()[1])/1024,1)
 except (OSError,ValueError,IndexError): pass
 return None

def mono_float32(value):
 import numpy as np
 if hasattr(value,"detach"): value=value.detach().cpu().numpy()
 audio=np.squeeze(np.asarray(value,dtype=np.float32))
 if audio.ndim==2:
  if audio.shape[0] in (1,2) and audio.shape[1]>2: audio=audio.mean(axis=0)
  elif audio.shape[1] in (1,2) and audio.shape[0]>2: audio=audio.mean(axis=1)
  else: raise ValueError(f"Unexpected audio shape {audio.shape}")
 if audio.ndim!=1 or not audio.size or not np.isfinite(audio).all(): raise ValueError("Invalid waveform.")
 if float(np.max(np.abs(audio)))<1e-5: raise ValueError("Model generated silence.")
 return audio

def write_blind_review(folder,rows):
 sections="\n".join(f'<section><h2>{r["blind_id"]}</h2><audio controls preload="none" src="{r["file_name"]}"></audio></section>' for r in rows)
 page=('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
 '<title>Anonymous voice review</title><style>body{font:16px system-ui;max-width:760px;margin:32px auto;padding:0 18px}audio{width:100%}section{padding:18px 0;border-bottom:1px solid #ddd}</style>'
 '<h1>Anonymous VoiceStudio listening review</h1><p>Listen without guessing the voice design. Score each sample in the CSV.</p>'+sections+'</html>')
 (folder/"index.html").write_text(page,encoding="utf-8")
 with (folder/"human-review.csv").open("w",newline="",encoding="utf-8") as f:
  w=csv.DictWriter(f,fieldnames=["blind_id","language","naturalness_1_5","pronunciation_1_5","prosody_1_5","voice_fit_1_5","notes"]); w.writeheader()
  for r in rows: w.writerow({"blind_id":r["blind_id"],"language":r["language"],"naturalness_1_5":"","pronunciation_1_5":"","prosody_1_5":"","voice_fit_1_5":"","notes":""})

def run(output):
 import soundfile as sf
 import torch
 from huggingface_hub import HfApi,snapshot_download
 from voxcpm import VoxCPM
 validate_contract()
 if importlib.metadata.version("voxcpm") != PACKAGE_VERSION: raise RuntimeError("Install pinned voxcpm==2.0.3.")
 output.mkdir(parents=True,exist_ok=True)
 raw=output/"raw"; normalized=output/"normalized"; blind=output/"blind-review"; analysis_dir=output/"analysis"
 for p in (raw,normalized,blind,analysis_dir): p.mkdir(parents=True,exist_ok=True)

 print(f"[VoxCPM2] Resolve immutable model revision: {MODEL_ID}",flush=True)
 revision=HfApi().model_info(MODEL_ID,files_metadata=False).sha
 if not isinstance(revision,str) or len(revision)!=40: raise RuntimeError("Invalid Hugging Face commit SHA.")
 model_dir=snapshot_download(repo_id=MODEL_ID,revision=revision)
 torch.set_num_threads(max(1,int(os.environ.get("OMP_NUM_THREADS","4"))))
 torch.set_num_interop_threads(1)
 started=time.perf_counter()
 model=VoxCPM.from_pretrained(str(model_dir),load_denoiser=False,local_files_only=True,device="cpu",optimize=False)
 load_seconds=time.perf_counter()-started
 rate=int(model.tts_model.sample_rate)
 if rate!=SAMPLE_RATE: raise RuntimeError(f"Expected 48 kHz native output, got {rate}.")
 print(f"[VoxCPM2] CPU model loaded in {load_seconds:.1f}s; runner RAM={memory_mib()} MiB; peak RSS={rss_mib()} MiB",flush=True)

 samples=[]; mapping=[]; total=0.0; n=0
 for identity in IDENTITIES:
  for lang in ("vi","en"):
   for text_no,utterance in enumerate(UTTERANCES[lang],1):
    n+=1; blind_id=f"sample_{n:02d}"; raw_path=raw/f"{blind_id}.wav"
    prompt=f'({identity["description"]}){utterance}'
    t0=time.perf_counter()
    waveform=model.generate(text=prompt,cfg_value=CFG_VALUE,inference_timesteps=INFERENCE_TIMESTEPS,normalize=True,retry_badcase=False,seed=identity["seed"])
    elapsed=time.perf_counter()-t0; total+=elapsed
    audio=mono_float32(waveform)
    sf.write(str(raw_path),audio,rate,format="WAV",subtype="PCM_24")
    duration=len(audio)/rate
    if not 3<=duration<=45: raise RuntimeError(f"{blind_id}: implausible duration {duration:.2f}s")
    row={"blind_id":blind_id,"language":lang,"file_name":f"{blind_id}.wav","duration_seconds":round(duration,3),"generation_seconds":round(elapsed,3),"rtfx":round(duration/max(elapsed,1e-6),4)}
    samples.append(row)
    mapping.append({**row,"identity_id":identity["id"],"identity_label":identity["label"],"utterance_index":text_no,"text":utterance,"voice_design_prompt":identity["description"],"seed":identity["seed"],"raw_sha256":digest(raw_path)})
    print(f"[VoxCPM2] {blind_id} {lang}: {duration:.1f}s audio / {elapsed:.1f}s synthesis, RTFx={row['rtfx']:.3f}, peak RSS={rss_mib()} MiB",flush=True)
 peak_rss_after_generation=rss_mib()

 # Release the 2B TTS model before loading AudioSeal on the CPU runner.
 del model; gc.collect()
 if torch.cuda.is_available(): torch.cuda.empty_cache()
 builder=load_builder(); verification={}
 for row in samples:
  src=raw/f'{row["blind_id"]}.wav'; dst=normalized/row["file_name"]
  builder.run_ffmpeg_normalize(src,dst,SAMPLE_RATE,24)
  mark=builder.watermark_and_verify(dst,24,context="voxcpm2.local_cpu_benchmark")
  checks=builder.validate_audio(dst,SAMPLE_RATE,24)
  row["sha256"]=digest(dst); row["watermark"]="verified"; row["watermark_confidence"]=mark.get("watermark_confidence")
  row["audio_validation"]=checks; shutil.copy2(dst,blind/row["file_name"])
  verification[row["blind_id"]]={"watermark":mark,"audio_validation":checks,"sha256":row["sha256"]}
 write_blind_review(blind,samples)
 for f in raw.glob("*.wav"): f.unlink()

 summary={"benchmark":"VoiceStudio local VoxCPM2 CPU design screening","status":"technically_validated_not_human_approved","generated_at_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"model_id":MODEL_ID,"model_revision":revision,"model_license":MODEL_LICENSE,"package_version":PACKAGE_VERSION,"device":"cpu","torch_version":str(torch.__version__),"python_version":platform.python_version(),"platform":platform.platform(),"logical_cpu_count":os.cpu_count(),"system_memory_mib":memory_mib(),"peak_rss_mib_during_tts":peak_rss_after_generation,"model_load_seconds":round(load_seconds,3),"total_synthesis_seconds":round(total,3),"identity_count":len(IDENTITIES),"sample_count":len(samples),"languages":["en","vi"],"native_sample_rate":rate,"cfg_value":CFG_VALUE,"inference_timesteps":INFERENCE_TIMESTEPS,"samples":samples,"human_review":"not_completed","production_promotion":"blocked_pending_rights_and_native_listener_review","limitations":["Voice-design prompts create synthetic voice styles, not real speaker identities.","Prompt and seed reuse do not alone prove perceived identity consistency.","Signal checks and watermark detection do not measure human preference or naturalness."]}
 (analysis_dir/"benchmark.json").write_text(json.dumps({"summary":summary,"identity_designs":IDENTITIES,"sample_mapping":mapping,"verification":verification},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 (analysis_dir/"README.md").write_text("Analysis mapping, immutable model revision, synthesis times, hashes and watermark evidence. Human preference scores are not yet available.\n",encoding="utf-8")
 lines=["# VoxCPM2 local CPU benchmark","",f"- Model: {MODEL_ID}",f"- Revision: {revision}","- Device: CPU only",f"- Identities: {len(IDENTITIES)}",f"- Samples: {len(samples)}",f"- Model load: {load_seconds:.1f}s",f"- Total synthesis: {total:.1f}s",f"- Peak RSS during TTS: {peak_rss_after_generation:.1f} MiB","","| Sample | Language | Duration (s) | Synthesis (s) | RTFx |","|---|---|---:|---:|---:|"]
 lines += [f'| {r["blind_id"]} | {r["language"]} | {r["duration_seconds"]:.2f} | {r["generation_seconds"]:.2f} | {r["rtfx"]:.3f} |' for r in samples]
 lines += ["","Human listening is not complete; no production approval is implied."]
 (output/"SUMMARY.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
 print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
 return summary

def main():
 p=argparse.ArgumentParser(); p.add_argument("--check",action="store_true"); p.add_argument("--output",type=Path,default=Path("dist/voxcpm2-local")); a=p.parse_args()
 if a.check:
  validate_contract()
  print("VoxCPM2 local-only benchmark static checks: OK"); return 0
 run(a.output); return 0

if __name__=="__main__": raise SystemExit(main())

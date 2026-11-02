#!/usr/bin/env python3
"""Dependency-free tests for the local VoxCPM2 benchmark contract."""
from __future__ import annotations
import importlib.util, sys, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts"/"benchmark_voxcpm2_local.py"
SPEC=importlib.util.spec_from_file_location("benchmark_voxcpm2_local",SCRIPT)
assert SPEC and SPEC.loader
MODULE=importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name]=MODULE
SPEC.loader.exec_module(MODULE)

class LocalVoxCPM2Tests(unittest.TestCase):
 def test_contract_is_exactly_english_and_vietnamese(self):
  MODULE.validate_contract()
  self.assertEqual(set(MODULE.UTTERANCES),{"en","vi"})
 def test_identity_ids_are_unique_and_have_prompts(self):
  ids=[item["id"] for item in MODULE.IDENTITIES]
  self.assertEqual(len(ids),len(set(ids)))
  self.assertTrue(all(item["description"].strip() for item in MODULE.IDENTITIES))
 def test_same_designs_cover_both_languages_with_two_texts(self):
  self.assertEqual(len(MODULE.IDENTITIES),2)
  self.assertTrue(all(len(items)==2 for items in MODULE.UTTERANCES.values()))
 def test_open_local_model_without_provider_keys(self):
  self.assertEqual(MODULE.MODEL_ID,"openbmb/VoxCPM2")
  self.assertEqual(MODULE.MODEL_LICENSE,"Apache-2.0")
  source=SCRIPT.read_text(encoding="utf-8")
  for key in ("ELEVENLABS_API_KEY","GEMINI_API_KEY","XAI_API_KEY"):
   self.assertNotIn(key,source)
  self.assertNotIn("requests.post",source)
 def test_voxcpm2_cpu_job_is_manual_opt_in(self):
  workflow=(ROOT/".github"/"workflows"/"voice-library.yml").read_text(encoding="utf-8")
  self.assertIn("if: ${{ github.event_name == 'workflow_dispatch' && inputs.voxcpm2_benchmark == true }}",workflow)
  self.assertNotIn("github.event.pull_request.head.ref == 'feat/local-voxcpm2-cpu-design-benchmark'",workflow)

 def test_voice_design_does_not_clone_reference_audio(self):
  source=SCRIPT.read_text(encoding="utf-8")
  self.assertIn("model.generate(",source)
  self.assertIn("torch.manual_seed(int(seed))",source)
  self.assertNotIn('seed=identity["seed"]',source)
  self.assertNotIn("reference_wav_path=",source)
  self.assertNotIn("prompt_wav_path=",source)

if __name__=="__main__": unittest.main(verbosity=2)

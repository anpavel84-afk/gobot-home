"""Static-only, offline and non-hardware release gate for HOST-B WakeNet10."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import unittest


ROOT=Path(__file__).resolve().parent
MANIFEST=ROOT/"build-manifest-public.json"


class LocalWakeNet10Safety(unittest.TestCase):
    def test_source_matches_actual_isolated_compilation(self):
        doc=json.loads(MANIFEST.read_text(encoding="utf8"))
        for path,digest in doc["source_sha256"].items():
            with self.subTest(path=path):
                self.assertEqual(
                    hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest)
        self.assertEqual(doc["build_steps_total"],1187)
        self.assertEqual(doc["esp_idf"],"6.0.1")
        self.assertEqual(doc["esp_sr"],"2.6.2")

    def test_no_monika_weights_or_fake_training(self):
        doc=json.loads(MANIFEST.read_text(encoding="utf8"))
        self.assertFalse(doc["model_is_monika"])
        self.assertFalse(doc["model_monika_available"])
        self.assertEqual(doc["model"],"wn10_ru_privetesp")
        self.assertNotEqual(doc["model_actual_wake_phrase"].lower(),"моника")
        self.assertIn('DEMO_MODEL "wn10_ru_privetesp"',
                      (ROOT/"main"/"main.c").read_text())

    def test_binary_hashes_are_documented_not_committed(self):
        doc=json.loads(MANIFEST.read_text(encoding="utf8"))
        for info in doc["private_build_artifacts_not_in_git"].values():
            self.assertEqual(len(info["sha256"]),64)
            self.assertGreater(info["bytes"],0)
        self.assertFalse(list(ROOT.rglob("*.bin")))
        self.assertFalse(list(ROOT.rglob("*.elf")))
        self.assertFalse(doc["installed"])
        self.assertFalse(doc["flash_modified"])
        self.assertEqual(doc["paid_calls"],0)

    def test_official_poc_model_partition_is_distinct(self):
        csv=(ROOT/"partitions_poc.csv").read_text()
        self.assertIn("model, data, spiffs, 0x500000, 0x200000",csv)
        self.assertIn("factory, app, factory, 0x10000, 0x400000",csv)

    def test_proposal_does_not_overwrite_ota_boot_nvs(self):
        csv=(ROOT/"partitions_proposal_rc1_NOT_FOR_FLASH.csv").read_text()
        rows={}
        for line in csv.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts=[x.strip() for x in line.split(",")]
            name,off,size=parts[0],int(parts[3],0),int(parts[4],0)
            self.assertNotIn(name,rows)
            rows[name]=(off,size)
        self.assertEqual(rows["nvs"],(0x9000,0x4000))
        self.assertEqual(rows["otadata"],(0xD000,0x2000))
        self.assertEqual(rows["phy_init"],(0xF000,0x1000))
        self.assertEqual(rows["ota_0"],(0x20000,0x3F0000))
        self.assertEqual(rows["ota_1"],(0x410000,0x3F0000))
        self.assertEqual(rows["assets"],(0x800000,0x600000))
        self.assertEqual(rows["model"],(0xE00000,0x200000))
        intervals=sorted((start,start+size,name)
                         for name,(start,size) in rows.items())
        for lhs,rhs in zip(intervals,intervals[1:]):
            self.assertLessEqual(lhs[1],rhs[0])
        self.assertEqual(max(e for _,e,_ in intervals),0x1000000)

    def test_contract_refuses_to_fake_touch_and_second_reader(self):
        text=(ROOT/"integration"/"CONTRACT.md").read_text()
        self.assertIn("not a change to HOST-A",text)
        self.assertIn("another I2S",text)
        self.assertIn("gobot_host_local_wake",text)
        self.assertIn("IS NOT SUPPORTED",text)
        self.assertIn("PLAN_STREAM",text)


if __name__=="__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-only
"""测试数据边界、暂停导出和过期计划取消。"""
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
import zipfile
import numpy as np
from fisher.config import DEFAULTS, hotkey_vk
from fisher.controller import Controller, Decision
from fisher.runtime import Runtime
from fisher.trial_capture import TrialRecorder
from fisher.packaging import MissingPublicFileError
from test_contact import observation

# 历史策略回归显式使用其原始配置；正式默认策略见test_phase。
DEFAULTS = dict(DEFAULTS,timing_mode="contact",capture_every_n_frames=6)


class Window:
    interrupted = False
    last_key_down_at = last_key_up_at = last_send_begin = last_send_end = None
    down = set()
    taps = 0
    def key_down(self,key): return key in self.down
    def foreground_matches(self,hwnd): return True
    def client_box(self,hwnd): return (0,0,336,598)
    def release(self): pass
    def tap_space(self,hwnd,hold,cancel,guard):
        if cancel() or not guard(): return False
        self.taps += 1
        self.last_send_begin = self.last_key_down_at = time.perf_counter()
        self.last_send_end = self.last_key_up_at = time.perf_counter()
        return True


class TrialTests(unittest.TestCase):
    def test_pause_zip_has_only_allowed_numeric_data_bar_crops_and_public_source(self):
        private = uuid.uuid4().hex
        cfg = dict(DEFAULTS,profile={"title":private},unexpected=private)
        with tempfile.TemporaryDirectory() as tmp:
            r = TrialRecorder(tmp)
            r.start(cfg)
            c = Controller(cfg)
            # Outside the bar crop is deliberately nonzero and must not be stored.
            frame = np.full((598,336,3),255,np.uint8)
            frame[376:426,77:266] = 0
            now = time.perf_counter()
            obs = observation(100)
            r.frame(obs,Decision(round_id=1),c,frame,now,now+.003,1,2)
            win = Window()
            win.last_key_down_at = now-20
            r.input("HIT",now,win,False,"stale_frame")
            r.finish()
            r.join()
            self.assertIsNone(r.last_error)
            with zipfile.ZipFile(r.last_bundle) as z:
                meta = json.loads(z.read("meta.json"))
                self.assertNotIn("profile",meta["settings"])
                self.assertEqual(meta["crop_count"],1)
                events = [json.loads(x) for x in z.read("events_000.jsonl").splitlines()]
                self.assertIsNone(events[1]["key_down_at"])
                self.assertFalse(any(private.encode() in z.read(n) for n in z.namelist()))
                self.assertIn("source/fisher/contact.py",z.namelist())
                import cv2
                crop = cv2.imdecode(np.frombuffer(z.read("crops/frame_00000000.png"),np.uint8),1)
                self.assertEqual(crop.shape,(50,189,3))
                self.assertEqual(int(crop.max()),0)
                for line in z.read("SHA256SUMS").decode().splitlines():
                    digest,name = line.split("  ",1)
                    self.assertEqual(sha256(z.read(name)).hexdigest(),digest)

    def test_custom_pause_key_exports_once_and_resume_creates_new_session(self):
        cfg = dict(DEFAULTS,pause_hotkey="F7")
        win = Window()
        r = Runtime(win,1,{"client_size":[336,598],"crop":[0,0,336,598]},cfg)
        c = Controller(cfg)
        with tempfile.TemporaryDirectory() as tmp:
            r.trial = TrialRecorder(tmp,r.emit)
            r.activate(c,time.perf_counter())
            self.assertTrue(r.active)
            win.down = {hotkey_vk("F7")}
            for cmd in r.hotkeys.poll(win.key_down): r.command(cmd)
            r.process_controls(c,time.perf_counter())
            self.assertFalse(r.active)
            r.trial.join()
            self.assertEqual(len(list((Path(tmp)/"trial_exports").glob("*.zip"))),1)
            r.pause("已暂停")
            r.trial.join()
            self.assertEqual(len(list((Path(tmp)/"trial_exports").glob("*.zip"))),1)
            win.down = set()
            r.activate(c,time.perf_counter())
            r.pause("已暂停")
            r.trial.join()
            self.assertEqual(len(list((Path(tmp)/"trial_exports").glob("*.zip"))),2)

    def test_stale_cancelled_and_distant_plans_never_tap(self):
        for mode in ("stale","cancelled","distant"):
            win = Window()
            r = Runtime(win,1,{"client_size":[336,598],"crop":[0,0,336,598]},DEFAULTS)
            r.active = True
            c = Controller(DEFAULTS)
            now = time.perf_counter()
            frame_time = now-.2 if mode == "stale" else now
            due = now+.1 if mode == "distant" else now+.01
            if mode == "cancelled": win.down = {hotkey_vk("F9")}
            self.assertFalse(r.dispatch(Decision(action="HIT",send_at=due),c,r.capture_box(),frame_time,now))
            self.assertEqual(win.taps,0)

    def test_timely_click_commits_once_and_learns_measured_host_delay(self):
        win = Window()
        r = Runtime(win,1,{"client_size":[336,598],"crop":[0,0,336,598]},DEFAULTS)
        r.active = True
        c = Controller(DEFAULTS)
        c.contact.target = (172,244)
        # 不让 Windows 的真实等待粒度决定 8ms 时效保护是否触发。
        clock = [1000.0]
        def advance(seconds):
            clock[0] += seconds
        now = clock[0]
        with patch("fisher.runtime.time.perf_counter", lambda: clock[0]), \
             patch.object(r.stop, "wait", side_effect=advance):
            self.assertTrue(r.dispatch(Decision(action="HIT",send_at=now+.005),c,r.capture_box(),now,now))
        self.assertTrue(c.contact.locked)
        self.assertEqual(win.taps,1)
        self.assertEqual(len(c.latency.samples),1)

    def test_overslept_contact_deadline_never_commits_or_learns(self):
        win = Window()
        r = Runtime(win, 1, {"client_size": [336,598], "crop": [0,0,336,598]}, DEFAULTS)
        r.active = True
        c = Controller(DEFAULTS)
        clock = [1000.0]
        def oversleep(seconds):
            clock[0] += seconds + .020
        now = clock[0]
        with patch("fisher.runtime.time.perf_counter", lambda: clock[0]), \
             patch.object(r.stop, "wait", side_effect=oversleep):
            self.assertFalse(r.dispatch(Decision(action="HIT", send_at=now+.005), c, r.capture_box(), now, now))
        self.assertEqual(win.taps, 0)
        self.assertEqual(len(c.latency.samples), 0)
        self.assertTrue(r.active)

    def test_export_failures_keep_safe_reason_and_raw_records_then_recover(self):
        private = uuid.uuid4().hex
        cases = ((MissingPublicFileError(".github/workflows/windows-portable.yml"), "missing_public_file"),
                 (PermissionError(private), "permission_denied"),
                 (RuntimeError(private), "export_failed"))
        for exception, code in cases:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                recorder = TrialRecorder(tmp)
                recorder.start(DEFAULTS)
                with patch("fisher.trial_capture.source_payloads", side_effect=exception):
                    recorder.finish()
                    recorder.join()
                self.assertEqual(recorder.last_error_info["code"], code)
                self.assertNotIn(private, recorder.last_error)
                error_file = next(Path(tmp).glob("trial_records/*/export_error.json"))
                self.assertNotIn(private, error_file.read_text(encoding="utf-8"))
                self.assertTrue(error_file.with_name("events_000.jsonl").exists())
                self.assertFalse(list(Path(tmp).rglob("*.zip.tmp")))
                recorder.start(DEFAULTS)
                recorder.finish()
                recorder.join()
                self.assertIsNone(recorder.last_error)
                self.assertIsNone(recorder.last_error_info)
                self.assertTrue(recorder.last_bundle.is_file())


if __name__ == "__main__": unittest.main()

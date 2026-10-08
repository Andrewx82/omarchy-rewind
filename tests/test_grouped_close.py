import copy
import importlib.machinery
import importlib.util
import json
import re
import subprocess
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "rewind"
loader = importlib.machinery.SourceFileLoader("rewind", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
rewind = importlib.util.module_from_spec(spec)
loader.exec_module(rewind)


class WindowManager:
    """Model Hyprland's group-wide workspace moves and individual closes."""

    def __init__(self, count=3):
        self.clients = {}
        addresses = [f"0x{i + 1:x}" for i in range(count)]
        for address in addresses:
            self.clients[address] = {
                "address": address,
                "title": f"Test {address}",
                "class": "test-terminal",
                "workspace": {"id": 1, "name": "1"},
                "grouped": addresses.copy(),
                "floating": False,
                "at": [10, 20],
                "size": [800, 400],
                "pid": int(address, 16) + 1000,
            }
        self.active = addresses[-1]
        self.detach_allowed = True
        self.join_allowed = True
        self.ignore_close = False
        self.commands = []

    def active_window(self):
        return copy.deepcopy(self.clients.get(self.active))

    def all_clients(self):
        return copy.deepcopy(list(self.clients.values()))

    def dispatch(self, command):
        self.commands.append(command)
        selector = re.search(r'window = "address:([^"]+)"', command)
        address = selector.group(1) if selector else self.active
        client = self.clients.get(address)
        if not client:
            return False
        if "out_of_group = true" in command:
            if not self.detach_allowed:
                return False
            for member in client["grouped"]:
                if member != address:
                    self.clients[member]["grouped"].remove(address)
            client["grouped"] = []
        elif "hl.dsp.window.move" in command:
            workspace = re.search(r'workspace = "([^"]+)"', command).group(1)
            for member in client["grouped"] or [address]:
                self.clients[member]["workspace"]["name"] = workspace
        elif "hl.dsp.window.close" in command:
            if not self.ignore_close:
                for member in client["grouped"]:
                    if member != address:
                        self.clients[member]["grouped"].remove(address)
                del self.clients[address]
        elif "hl.dsp.window.kill" in command:
            for member in client["grouped"]:
                if member != address:
                    self.clients[member]["grouped"].remove(address)
            del self.clients[address]
        elif "hl.dsp.window.float" in command:
            client["floating"] = 'action = "enable"' in command
        elif "hl.dsp.group.toggle" in command:
            if client["grouped"]:
                for member in client["grouped"].copy():
                    self.clients[member]["grouped"] = []
            else:
                client["grouped"] = [address]
        elif "hl.dsp.focus" in command:
            self.active = address
        else:
            raise AssertionError(f"Unexpected dispatcher: {command}")
        return True

    def evaluate(self, code):
        self.commands.append(code)
        if "out_of_group = true" in code:
            if not self.detach_allowed:
                return False
            address = re.search(r'hl.get_window\("address:([^"]+)"\)', code).group(1)
            client = self.clients[address]
            for member in client["grouped"]:
                if member != address:
                    self.clients[member]["grouped"].remove(address)
            client["grouped"] = []
            client["floating"] = True
            client["workspace"]["name"] = "special:rewind"
            return True
        if "toggle_special" in code or "hl.get_workspace_windows" in code:
            return True
        if not self.join_allowed:
            return False
        address, peer = re.findall(r'hl.get_window\("address:([^"]+)"\)', code)
        index = int(re.search(r'math.min\((\d+), group.size', code).group(1)) - 1
        group = self.clients[peer]["grouped"].copy()
        group.insert(index, address)
        workspace = self.clients[peer]["workspace"].copy()
        floating = self.clients[peer]["floating"]
        for member in group:
            self.clients[member]["grouped"] = group.copy()
            self.clients[member]["workspace"] = workspace.copy()
            self.clients[member]["floating"] = floating
        return True


class GroupedCloseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        self.wm = WindowManager()
        self.state = {
            "enabled": True,
            "countdown_enabled": False,
            "countdown_seconds": 15,
            "pause_media": True,
            "queue": [],
        }
        self.state_file = directory / "state.json"
        self.save_state()
        replacements = {
            "STATE_DIR": directory,
            "STATE_FILE": self.state_file,
            "LOCK_FILE": directory / "state.lock",
            "get_active_window": self.wm.active_window,
            "get_all_clients": self.wm.all_clients,
            "hypr_dispatch": self.wm.dispatch,
            "hypr_eval": self.wm.evaluate,
        }
        for name, value in replacements.items():
            patcher = patch.object(rewind, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ("show_osd", "notify_shell_widget", "pause_window_media", "mute_window_audio", "unmute_window_audio", "prepare_window_audio_for_close"):
            patcher = patch.object(rewind, name, return_value=None)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        patcher = patch.object(rewind.subprocess, "Popen")
        self.worker = patcher.start()
        self.addCleanup(patcher.stop)

    def save_state(self):
        self.state_file.write_text(json.dumps(self.state))

    def queue(self):
        return json.loads(self.state_file.read_text())["queue"]

    def assert_remaining_group(self):
        for address in ("0x1", "0x2"):
            self.assertEqual(self.wm.clients[address]["workspace"]["name"], "1")
            self.assertEqual(self.wm.clients[address]["grouped"], ["0x1", "0x2"])

    def test_manual_close_hides_only_selected_member_and_restore_keeps_peers(self):
        rewind.action_close()
        self.assert_remaining_group()
        self.assertEqual(self.wm.clients["0x3"]["workspace"]["name"], "special:rewind")
        self.assertEqual(self.wm.clients["0x3"]["grouped"], [])
        self.assertEqual([item["address"] for item in self.queue()], ["0x3"])
        self.worker.assert_not_called()

        rewind.action_restore()
        for client in self.wm.clients.values():
            self.assertEqual(client["grouped"], ["0x1", "0x2", "0x3"])
        self.assertEqual(self.wm.clients["0x3"]["workspace"]["name"], "1")
        self.assertEqual(self.wm.active, "0x3")
        self.assertEqual(self.queue(), [])

    def test_tiled_tab_keeps_geometry_while_hidden_and_rejoins_tiled(self):
        before = self.wm.active_window()
        rewind.action_close()
        hidden = self.wm.clients["0x3"]
        self.assertTrue(hidden["floating"])
        self.assertEqual(hidden["at"], before["at"])
        self.assertEqual(hidden["size"], before["size"])
        self.assertFalse(self.queue()[0]["group_floating"])
        # The detach and workspace move must use the same compositor request.
        transitions = [command for command in self.wm.commands if "out_of_group" in command]
        self.assertEqual(len(transitions), 1)
        self.assertIn('workspace = "special:rewind"', transitions[0])
        rewind.action_restore()
        self.assertFalse(self.wm.clients["0x3"]["floating"])

    def test_floating_group_retains_floating_mode(self):
        for client in self.wm.clients.values():
            client["floating"] = True
        rewind.action_close()
        self.assertTrue(self.queue()[0]["group_floating"])
        rewind.action_restore()
        self.assertTrue(self.wm.clients["0x3"]["floating"])

    def test_dissolved_floating_group_restores_independent_floating_window(self):
        for client in self.wm.clients.values():
            client["floating"] = True
        rewind.action_close()
        self.wm.dispatch('hl.dsp.group.toggle({ window = "address:0x1" })')
        rewind.action_restore()
        self.assertTrue(self.wm.clients["0x3"]["floating"])
        self.assertEqual(self.wm.clients["0x3"]["grouped"], [])

    def test_countdown_expires_only_selected_member(self):
        self.state["countdown_enabled"] = True
        self.save_state()
        with patch.object(rewind.time, "time", return_value=100):
            rewind.action_close()
        self.assert_remaining_group()
        self.worker.assert_called_once()
        with patch.object(rewind.time, "sleep"), patch.object(rewind.time, "time", return_value=116):
            rewind.action_expire("0x3", "100", "15")
        self.assert_remaining_group()
        self.assertNotIn("0x3", self.wm.clients)
        self.assertEqual(self.queue(), [])

    def test_restore_first_middle_and_last_at_original_index(self):
        for index, address in enumerate(("0x1", "0x2", "0x3")):
            with self.subTest(index=index):
                self.wm.active = address
                rewind.action_close()
                self.assertEqual(self.queue()[0]["group_members"], ["0x1", "0x2", "0x3"])
                rewind.action_restore()
                for client in self.wm.clients.values():
                    self.assertEqual(client["grouped"], ["0x1", "0x2", "0x3"])
                self.assertEqual(self.wm.active, address)

    def test_restore_all_queued_members_reconstructs_original_group_order(self):
        self.state["countdown_enabled"] = True
        self.save_state()
        for address in ("0x1", "0x2", "0x3"):
            self.wm.active = address
            rewind.action_close()
        for expected in (["0x3"], ["0x2", "0x3"], ["0x1", "0x2", "0x3"]):
            rewind.action_restore()
            for address in expected:
                self.assertEqual(self.wm.clients[address]["grouped"], expected)
        self.assertEqual(self.queue(), [])

    def test_missing_predecessor_restores_before_surviving_successor(self):
        self.wm.active = "0x2"
        rewind.action_close()
        self.wm.dispatch('hl.dsp.window.close({ window = "address:0x1" })')
        rewind.action_restore()
        for client in self.wm.clients.values():
            self.assertEqual(client["grouped"], ["0x2", "0x3"])

    def test_dissolved_group_restores_window_separately(self):
        rewind.action_close()
        self.wm.dispatch('hl.dsp.group.toggle({ window = "address:0x1" })')
        rewind.action_restore()
        self.assertEqual(self.wm.clients["0x3"]["grouped"], [])
        self.assertEqual(self.wm.clients["0x3"]["workspace"]["name"], "1")
        self.assertFalse(self.wm.clients["0x3"]["floating"])
        self.assertIn("Group unavailable", self.show_osd.call_args.args[1])

    def test_failed_join_restores_window_separately_without_changing_peers(self):
        rewind.action_close()
        self.wm.join_allowed = False
        rewind.action_restore()
        self.assert_remaining_group()
        self.assertEqual(self.wm.clients["0x3"]["grouped"], [])
        self.assertEqual(self.wm.clients["0x3"]["workspace"]["name"], "1")
        self.assertEqual(self.queue(), [])

    def test_old_queue_record_without_group_metadata_still_restores(self):
        rewind.action_close()
        state = json.loads(self.state_file.read_text())
        del state["queue"][0]["group_members"]
        self.state_file.write_text(json.dumps(state))
        rewind.action_restore()
        self.assert_remaining_group()
        self.assertEqual(self.wm.clients["0x3"]["workspace"]["name"], "1")

    def test_group_moved_while_hidden_restores_to_groups_current_workspace(self):
        rewind.action_close()
        self.wm.dispatch('hl.dsp.window.move({ window = "address:0x1", workspace = "2" })')
        rewind.action_restore()
        for client in self.wm.clients.values():
            self.assertEqual(client["workspace"]["name"], "2")
            self.assertEqual(client["grouped"], ["0x1", "0x2", "0x3"])

    def test_two_member_group_keeps_other_member_on_workspace(self):
        del self.wm.clients["0x2"]
        for client in self.wm.clients.values():
            client["grouped"] = ["0x1", "0x3"]
        rewind.action_close()
        self.assertEqual(self.wm.clients["0x1"]["workspace"]["name"], "1")
        self.assertEqual(self.wm.clients["0x1"]["grouped"], ["0x1"])
        self.assertEqual(self.wm.clients["0x3"]["workspace"]["name"], "special:rewind")

    def test_single_member_group_is_detached(self):
        self.wm.dispatch('hl.dsp.window.move({ window = "address:0x3", out_of_group = true })')
        self.wm.commands.clear()
        self.wm.clients["0x3"]["grouped"] = ["0x3"]
        rewind.action_close()
        self.assertEqual(self.wm.clients["0x3"]["grouped"], [])
        self.assertEqual(self.wm.clients["0x3"]["workspace"]["name"], "special:rewind")

    def test_ungrouped_window_still_closes_without_detach(self):
        self.wm.dispatch('hl.dsp.window.move({ window = "address:0x3", out_of_group = true })')
        self.wm.commands.clear()
        rewind.action_close()
        self.assertFalse(any("out_of_group" in command for command in self.wm.commands))
        self.assertEqual(self.wm.clients["0x3"]["workspace"]["name"], "special:rewind")
        self.assertEqual([item["address"] for item in self.queue()], ["0x3"])

    def test_failed_detach_preserves_windows_queue_and_media(self):
        self.wm.detach_allowed = False
        before = self.wm.all_clients()
        rewind.action_close()
        self.assertEqual(self.wm.all_clients(), before)
        self.assertEqual(self.queue(), [])
        self.pause_window_media.assert_not_called()
        self.worker.assert_not_called()
        self.show_osd.assert_called_once()

    def test_disabled_rewind_permanently_closes_only_selected_member(self):
        self.state["enabled"] = False
        self.save_state()
        rewind.action_close()
        self.assert_remaining_group()
        self.assertNotIn("0x3", self.wm.clients)
        self.assertEqual(self.queue(), [])

    def test_hidden_window_permanently_closes_without_detach(self):
        self.wm.dispatch('hl.dsp.window.move({ window = "address:0x3", out_of_group = true })')
        self.wm.commands.clear()
        self.wm.clients["0x3"]["workspace"]["name"] = "special:rewind"
        rewind.action_close()
        self.assert_remaining_group()
        self.assertNotIn("0x3", self.wm.clients)
        self.assertEqual(self.queue(), [])

    def test_close_flushes_workspace_focus(self):
        rewind.action_close()
        self.assertTrue(any("hl.get_workspace_windows" in command for command in self.wm.commands))

    def test_queued_hidden_window_refreshes_grace_without_destroy(self):
        self.state["queue"] = [{
            "address": "0x3",
            "workspace": "1",
            "title": "Test 0x3",
            "class": "test-terminal",
            "timestamp": 1000.0,
            "expires_at": 1015.0,
            "paused_media": None,
            "group_members": ["0x1", "0x2", "0x3"],
            "group_floating": False
        }]
        self.state["countdown_enabled"] = True
        self.save_state()
        self.wm.clients["0x3"]["workspace"]["name"] = "special:rewind"
        rewind.action_close()
        self.assertIn("0x3", self.wm.clients)
        queue = self.queue()
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["address"], "0x3")
        self.assertGreater(queue[0]["expires_at"], 1015.0)
        self.show_osd.assert_called_once()

    def test_restore_ensures_special_workspace_closed(self):
        self.state["queue"] = [{
            "address": "0x3",
            "workspace": "1",
            "title": "Test 0x3",
            "class": "test-terminal",
            "timestamp": 1000.0,
            "expires_at": None,
            "paused_media": None,
            "group_members": ["0x1", "0x2", "0x3"],
            "group_floating": False
        }]
        self.save_state()
        self.wm.clients["0x3"]["workspace"]["name"] = "special:rewind"
        rewind.action_restore()
        self.assertTrue(any("toggle_special" in command for command in self.wm.commands))

    def test_restore_does_not_leak_window_title_to_osd(self):
        self.state["queue"] = [{
            "address": "0x3",
            "workspace": "1",
            "title": "Confidential Document Title",
            "class": "test-terminal",
            "timestamp": 1000.0,
            "expires_at": None,
            "paused_media": None,
            "group_members": [],
            "group_floating": False
        }]
        self.save_state()
        rewind.action_restore()
        self.show_osd.assert_called_once()
        osd_msg = self.show_osd.call_args.args[1]
        self.assertNotIn("Confidential Document Title", osd_msg)
        self.assertEqual(osd_msg, "Rewound window")


class DispatcherTests(unittest.TestCase):
    def test_only_ok_response_counts_as_success(self):
        for code, output, expected in (
            (0, "ok\n", True),
            (0, "info: =[C]:-1: Groups locked\n", False),
            (0, "", False),
            (1, "ok\n", False),
        ):
            with self.subTest(code=code, output=output):
                result = subprocess.CompletedProcess([], code, stdout=output, stderr="")
                with patch.object(rewind.subprocess, "run", return_value=result):
                    self.assertEqual(rewind.hypr_dispatch("hl.dsp.window.move({ out_of_group = true })"), expected)


class TerminationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.wm = WindowManager()
        self.state = {
            "enabled": True,
            "countdown_enabled": True,
            "countdown_seconds": 15,
            "pause_media": True,
            "queue": [],
        }
        self.state_file = self.directory / "state.json"
        self.state_file.write_text(json.dumps(self.state))
        replacements = {
            "STATE_DIR": self.directory,
            "STATE_FILE": self.state_file,
            "LOCK_FILE": self.directory / "state.lock",
            "get_active_window": self.wm.active_window,
            "get_all_clients": self.wm.all_clients,
            "hypr_dispatch": self.wm.dispatch,
            "hypr_eval": self.wm.evaluate,
        }
        for name, value in replacements.items():
            patcher = patch.object(rewind, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ("show_osd", "notify_shell_widget", "pause_window_media", "mute_window_audio", "unmute_window_audio", "prepare_window_audio_for_close"):
            patcher = patch.object(rewind, name, return_value=None)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        patcher = patch.object(rewind.subprocess, "Popen")
        self.worker = patcher.start()
        self.addCleanup(patcher.stop)

    def test_terminate_window_graceful_close(self):
        # Window responds to window.close immediately
        rewind.terminate_window("0x3", 1003)
        self.assertNotIn("0x3", self.wm.clients)
        close_cmds = [c for c in self.wm.commands if "hl.dsp.window.close" in c and "0x3" in c]
        kill_cmds = [c for c in self.wm.commands if "hl.dsp.window.kill" in c and "0x3" in c]
        self.assertEqual(len(close_cmds), 1)
        self.assertEqual(len(kill_cmds), 0)

    def test_terminate_window_fallback_to_force_kill(self):
        # Window ignores window.close; compositor force kill is invoked
        self.wm.ignore_close = True
        with patch.object(rewind.time, "sleep"):
            rewind.terminate_window("0x3", 1003)
        self.assertNotIn("0x3", self.wm.clients)
        close_cmds = [c for c in self.wm.commands if "hl.dsp.window.close" in c and "0x3" in c]
        kill_cmds = [c for c in self.wm.commands if "hl.dsp.window.kill" in c and "0x3" in c]
        self.assertEqual(len(close_cmds), 1)
        self.assertEqual(len(kill_cmds), 1)

    def test_terminate_window_signals_process_tree(self):
        signals_sent = []
        alive = {2000, 2001, 2002}

        def mock_kill(pid, sig):
            if sig == signal.SIGTERM:
                alive.discard(pid)
            elif sig == 0:
                if pid not in alive:
                    raise ProcessLookupError
                return
            signals_sent.append((pid, sig))

        with patch.object(rewind, "get_process_tree", return_value={2001, 2002}), \
             patch.object(rewind, "get_process_comm", return_value="game.exe"), \
             patch.object(rewind.os, "kill", side_effect=mock_kill), \
             patch.object(rewind.time, "sleep"):
            rewind.terminate_window("0x3", 2000)

        # Should send SIGTERM to root PID (2000) and descendants (2001, 2002)
        sigterm_pids = {pid for pid, sig in signals_sent if sig == signal.SIGTERM}
        self.assertEqual(sigterm_pids, {2000, 2001, 2002})
        sigkill_pids = {pid for pid, sig in signals_sent if sig == signal.SIGKILL}
        self.assertEqual(sigkill_pids, set())

    def test_terminate_window_force_kills_surviving_processes(self):
        signals_sent = []

        def mock_kill(pid, sig):
            signals_sent.append((pid, sig))

        with patch.object(rewind, "get_process_tree", return_value={2001}), \
             patch.object(rewind, "get_process_comm", return_value="game.exe"), \
             patch.object(rewind.os, "kill", side_effect=mock_kill), \
             patch.object(rewind.time, "sleep"):
            rewind.terminate_window("0x3", 2000)

        sigkill_pids = {pid for pid, sig in signals_sent if sig == signal.SIGKILL}
        self.assertEqual(sigkill_pids, {2000, 2001})

    def test_terminate_window_protects_multi_window_process(self):
        signals_sent = []

        def mock_kill(pid, sig):
            signals_sent.append((pid, sig))

        # Give 0x1 and 0x2 the same PID (multi-window app)
        self.wm.clients["0x1"]["pid"] = 9999
        self.wm.clients["0x2"]["pid"] = 9999

        with patch.object(rewind, "get_process_tree", return_value=set()), \
             patch.object(rewind, "get_process_comm", return_value="browser"), \
             patch.object(rewind.os, "kill", side_effect=mock_kill):
            rewind.terminate_window("0x1", 9999)

        # 0x1 is closed, but 9999 is spared because 0x2 still exists with pid 9999
        self.assertNotIn("0x1", self.wm.clients)
        self.assertIn("0x2", self.wm.clients)
        self.assertEqual(len(signals_sent), 0)

    def test_terminate_window_protects_steam_and_system_processes(self):
        signals_sent = []

        def mock_kill(pid, sig):
            signals_sent.append((pid, sig))

        with patch.object(rewind, "get_process_comm", return_value="steam"), \
             patch.object(rewind.os, "kill", side_effect=mock_kill):
            rewind.terminate_window("0x3", 1003)

        self.assertNotIn("0x3", self.wm.clients)
        self.assertEqual(len(signals_sent), 0)

    def test_action_close_stores_pid_in_record(self):
        self.wm.clients["0x3"]["pid"] = 4321
        rewind.action_close()
        queue = json.loads(self.state_file.read_text())["queue"]
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["pid"], 4321)

    def test_action_clear_terminates_all_queued(self):
        self.state["queue"] = [
            {"address": "0x1", "pid": 1001, "workspace": "1", "timestamp": 100},
            {"address": "0x2", "pid": 1002, "workspace": "1", "timestamp": 100},
        ]
        self.state_file.write_text(json.dumps(self.state))

        with patch.object(rewind, "terminate_window") as mock_term:
            rewind.action_clear()
            self.assertEqual(mock_term.call_count, 2)
            mock_term.assert_any_call("0x1", 1001)
            mock_term.assert_any_call("0x2", 1002)

        queue = json.loads(self.state_file.read_text())["queue"]
        self.assertEqual(queue, [])

    def test_action_toggle_off_terminates_all_queued(self):
        self.state["queue"] = [
            {"address": "0x3", "pid": 1003, "workspace": "1", "timestamp": 100},
        ]
        self.state_file.write_text(json.dumps(self.state))

        with patch.object(rewind, "terminate_window") as mock_term:
            rewind.action_toggle()
            mock_term.assert_called_once_with("0x3", 1003)

        queue = json.loads(self.state_file.read_text())["queue"]
        self.assertEqual(queue, [])

    def test_get_process_tree_finds_nested_descendants(self):
        fake_procs = {
            "100": "100 (proc) S 1",
            "101": "101 (proc) S 100",
            "102": "102 (proc) S 100",
            "103": "103 (proc) S 101",
            "104": "104 (proc) S 1",
            "105": "105 (proc) S 104",
        }
        class FakeEntry:
            def __init__(self, name):
                self.name = name
                self.path = f"/fake_proc/{name}"
            def is_dir(self):
                return True

        def fake_scandir(path):
            return [FakeEntry(name) for name in fake_procs]

        def fake_open(path, mode="r"):
            pid = Path(path).parent.name
            content = fake_procs.get(pid, "")
            import io
            return io.StringIO(content)

        with patch("os.scandir", side_effect=fake_scandir), \
             patch("builtins.open", side_effect=fake_open):
            tree = rewind.get_process_tree(100)
            self.assertEqual(tree, {101, 102, 103})


class AudioMuteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.wm = WindowManager()
        self.state = {
            "enabled": True,
            "countdown_enabled": True,
            "countdown_seconds": 15,
            "pause_media": True,
            "queue": [],
        }
        self.state_file = self.directory / "state.json"
        self.state_file.write_text(json.dumps(self.state))
        replacements = {
            "STATE_DIR": self.directory,
            "STATE_FILE": self.state_file,
            "LOCK_FILE": self.directory / "state.lock",
            "get_active_window": self.wm.active_window,
            "get_all_clients": self.wm.all_clients,
            "hypr_dispatch": self.wm.dispatch,
            "hypr_eval": self.wm.evaluate,
        }
        for name, value in replacements.items():
            patcher = patch.object(rewind, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ("show_osd", "notify_shell_widget", "pause_window_media"):
            patcher = patch.object(rewind, name, return_value=None)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        patcher = patch.object(rewind.subprocess, "Popen")
        self.worker = patcher.start()
        self.addCleanup(patcher.stop)

    def test_mute_window_audio_dispatches_wpctl_and_pactl(self):
        fake_pw_dump = [
            {
                "id": 50,
                "type": "PipeWire:Interface:Client",
                "info": {"props": {"application.process.id": 3000}},
            },
            {
                "id": 75,
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "media.class": "Stream/Output/Audio",
                        "client.id": 50,
                    }
                },
            },
        ]
        fake_pactl = (
            "Sink Input #12\n"
            "\tDriver: PipeWire\n"
            "\tProperties:\n"
            '\t\tapplication.process.id = "3000"\n'
        )

        run_cmds = []

        def fake_run(cmd, *args, **kwargs):
            run_cmds.append(cmd)
            if cmd[0] == "pw-dump":
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(fake_pw_dump), stderr="")
            elif len(cmd) >= 2 and cmd[:2] == ["pactl", "list"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=fake_pactl, stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch.object(rewind.subprocess, "run", side_effect=fake_run):
            result = rewind.mute_window_audio({"pid": 3000, "class": "game"})

        self.assertIsNotNone(result)
        self.assertIn(75, result["nodes"])
        self.assertIn(12, result["pactl"])

        self.assertTrue(any(cmd == ["wpctl", "set-mute", "75", "1"] for cmd in run_cmds))
        self.assertTrue(any(cmd == ["pactl", "set-sink-input-mute", "12", "1"] for cmd in run_cmds))

    def test_unmute_window_audio_dispatches_unmute(self):
        run_cmds = []

        def fake_run(cmd, *args, **kwargs):
            run_cmds.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch.object(rewind.subprocess, "run", side_effect=fake_run):
            rewind.unmute_window_audio({
                "pid": 3000,
                "class": "game",
                "muted_audio": {"nodes": [75], "pactl": [12]},
            })

        self.assertTrue(any(cmd == ["wpctl", "set-mute", "75", "0"] for cmd in run_cmds))
        self.assertTrue(any(cmd == ["pactl", "set-sink-input-mute", "12", "0"] for cmd in run_cmds))

    def test_action_close_mutes_audio_and_shows_osd(self):
        with patch.object(rewind, "mute_window_audio", return_value={"nodes": [75], "pactl": [12]}):
            rewind.action_close()

        queue = json.loads(self.state_file.read_text())["queue"]
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["muted_audio"], {"nodes": [75], "pactl": [12]})

        self.show_osd.assert_called_once()
        osd_msg = self.show_osd.call_args.args[1]
        self.assertIn("Audio muted", osd_msg)

    def test_action_restore_unmutes_audio_and_shows_osd(self):
        now = rewind.time.time()
        self.state["queue"] = [{
            "address": "0x3",
            "workspace": "1",
            "title": "Game",
            "class": "game",
            "pid": 1003,
            "timestamp": now,
            "expires_at": now + 100.0,
            "paused_media": None,
            "muted_audio": {"nodes": [75], "pactl": [12]},
            "group_members": [],
            "group_floating": False,
        }]
        self.state_file.write_text(json.dumps(self.state))
        self.wm.clients["0x3"]["workspace"]["name"] = "special:rewind"

        with patch.object(rewind, "unmute_window_audio") as mock_unmute:
            rewind.action_restore()
            mock_unmute.assert_called_once()
            target = mock_unmute.call_args.args[0]
            self.assertEqual(target["address"], "0x3")

        self.show_osd.assert_called_once()
        osd_msg = self.show_osd.call_args.args[1]
        self.assertIn("Audio unmuted", osd_msg)

    def test_prepare_window_audio_for_close_destroys_links_unmutes_and_sanitizes(self):
        fake_pw_dump = [
            {
                "id": 99,
                "type": "PipeWire:Interface:Link",
                "info": {"props": {"link.output.node": 75}},
            },
        ]
        run_cmds = []

        def fake_run(cmd, *args, **kwargs):
            run_cmds.append(cmd)
            if cmd[0] == "pw-dump":
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(fake_pw_dump), stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        wp_prop_dir = self.directory / ".local" / "state" / "wireplumber"
        wp_prop_dir.mkdir(parents=True, exist_ok=True)
        fake_wp_props = wp_prop_dir / "stream-properties"
        fake_wp_props.write_text('Output/Audio:application.name:game={"mute":true, "volume":1.0}\n')

        with patch.object(rewind.subprocess, "run", side_effect=fake_run), \
             patch("pathlib.Path.home", return_value=self.directory):
            rewind.prepare_window_audio_for_close({
                "pid": 3000,
                "class": "game",
                "muted_audio": {"nodes": [75], "pactl": [12]},
            })

        # Links destroyed
        self.assertTrue(any(cmd == ["pw-cli", "destroy", "99"] for cmd in run_cmds))
        # Unmute sent
        self.assertTrue(any(cmd == ["wpctl", "set-mute", "75", "0"] for cmd in run_cmds))
        self.assertTrue(any(cmd == ["pactl", "set-sink-input-mute", "12", "0"] for cmd in run_cmds))
        # Disk file sanitized
        self.assertIn('"mute":false', fake_wp_props.read_text())

    def test_action_expire_prepares_window_audio_for_close(self):
        now = rewind.time.time()
        self.state["queue"] = [{
            "address": "0x3",
            "workspace": "1",
            "title": "Game",
            "class": "game",
            "pid": 1003,
            "timestamp": now,
            "expires_at": now + 0.1,
            "paused_media": None,
            "muted_audio": {"nodes": [75], "pactl": [12]},
            "group_members": [],
            "group_floating": False,
        }]
        self.state_file.write_text(json.dumps(self.state))

        with patch.object(rewind, "prepare_window_audio_for_close") as mock_prep, \
             patch.object(rewind, "terminate_window"):
            rewind.action_expire("0x3", str(now), "0.0")
            mock_prep.assert_called_once()
            called_target = mock_prep.call_args.args[0]
            self.assertEqual(called_target["address"], "0x3")
            self.assertEqual(called_target["muted_audio"], {"nodes": [75], "pactl": [12]})

    def test_action_clear_prepares_window_audio_for_close(self):
        self.state["queue"] = [{
            "address": "0x3",
            "workspace": "1",
            "title": "Game",
            "class": "game",
            "pid": 1003,
            "timestamp": 100.0,
            "expires_at": None,
            "paused_media": None,
            "muted_audio": {"nodes": [75], "pactl": [12]},
            "group_members": [],
            "group_floating": False,
        }]
        self.state_file.write_text(json.dumps(self.state))

        with patch.object(rewind, "prepare_window_audio_for_close") as mock_prep, \
             patch.object(rewind, "terminate_window"):
            rewind.action_clear()
            mock_prep.assert_called_once()
            called_target = mock_prep.call_args.args[0]
            self.assertEqual(called_target["address"], "0x3")
            self.assertEqual(called_target["muted_audio"], {"nodes": [75], "pactl": [12]})

    def test_action_toggle_off_prepares_window_audio_for_close(self):
        self.state["queue"] = [{
            "address": "0x3",
            "workspace": "1",
            "title": "Game",
            "class": "game",
            "pid": 1003,
            "timestamp": 100.0,
            "expires_at": None,
            "paused_media": None,
            "muted_audio": {"nodes": [75], "pactl": [12]},
            "group_members": [],
            "group_floating": False,
        }]
        self.state_file.write_text(json.dumps(self.state))

        with patch.object(rewind, "prepare_window_audio_for_close") as mock_prep, \
             patch.object(rewind, "terminate_window"):
            rewind.action_toggle()
            mock_prep.assert_called_once()
            called_target = mock_prep.call_args.args[0]
            self.assertEqual(called_target["address"], "0x3")
            self.assertEqual(called_target["muted_audio"], {"nodes": [75], "pactl": [12]})


if __name__ == "__main__":
    unittest.main()

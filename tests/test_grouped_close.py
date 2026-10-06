import copy
import importlib.machinery
import importlib.util
import json
import re
import subprocess
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
            }
        self.active = addresses[-1]
        self.detach_allowed = True
        self.join_allowed = True
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
        for name in ("show_osd", "notify_shell_widget", "pause_window_media"):
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


if __name__ == "__main__":
    unittest.main()

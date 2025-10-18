import sublime
import sublime_plugin
import difflib
import os
from .settings import get_settings, get_tests_file_path

# 🟢 1. Run all tests command
class CpRunAllTestsCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        window = self.view.window()
        opd_view = next(
            (v for v in window.views() if v.settings().get("is_opd_view")), None
        )
        if opd_view:
            opd_view.run_command("test_manager", {"action": "run_all_tests"})
        else:
            sublime.status_message("No active run view found")

# 🟣 2. Open problem (shows current test file if available)
class CpOpenProblemCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        window = self.view.window()
        opd_view = next(
            (v for v in window.views() if v.settings().get("is_opd_view")), None
        )
        if not opd_view:
            sublime.status_message("No run view found")
            return

        run_file = getattr(opd_view, "dbg_file", None)
        if not run_file:
            # fallback if not set
            session = getattr(opd_view.run_command("test_manager", {}), "session", None)
            if session:
                run_file = session.get("run_file")

        if run_file and os.path.exists(run_file):
            window.open_file(run_file)
        else:
            sublime.status_message("No source file linked to this session")

# 🟠 3. Show diff between expected and actual output
class CpShowDiffCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        window = self.view.window()
        opd_view = next(
            (v for v in window.views() if v.settings().get("is_opd_view")), None
        )
        if not opd_view or not hasattr(opd_view, "dbg_file"):
            sublime.status_message("No run view found")
            return

        try:
            from .test_manager import TestManagerCommand
            tm = opd_view.run_command
        except Exception as e:
            sublime.error_message("Could not access test manager: " + str(e))
            return

        # load latest test data file
        try:
            tests_path = get_tests_file_path(opd_view.dbg_file)
            with open(tests_path, "r") as f:
                import json
                tests = json.load(f)
        except Exception:
            sublime.error_message("No saved test data found")
            return

        if not tests:
            sublime.status_message("No test data found")
            return

        # pick last test (most recent)
        test = tests[-1]
        expected = test.get("correct_answers", [""])[0]
        actual = opd_view.run_command("test_manager", {})  # placeholder

        diff_text = "\n".join(
            difflib.unified_diff(
                expected.splitlines(),
                actual.splitlines(),
                fromfile="expected",
                tofile="output",
                lineterm="",
            )
        )

        diff_view = window.new_file()
        diff_view.set_name("Diff View")
        diff_view.set_scratch(True)
        diff_view.assign_syntax("Packages/Diff/Diff.sublime-syntax")
        diff_view.run_command("append", {"characters": diff_text})
import base64
import json
import os
import re
import subprocess
import threading

import sublime
import sublime_plugin

from .settings import get_meta_file_path, get_settings

# All Codeforces language options: (id, display_name)
CF_LANGUAGES = [
    ("43",  "GNU GCC C11 5.1.0"),
    ("80",  "Clang++20 Diagnostics"),
    ("89",  "GNU G++20 13.2 (64 bit)"),
    ("90",  "GNU G++23 14.2 (64 bit)"),
    ("73",  "GNU G++17 7.3.0 (64 bit)"),
    ("52",  "Clang++17 Diagnostics"),
    ("50",  "GNU G++14 6.4.0"),
    ("31",  "Python 3.8.10"),
    ("40",  "PyPy 2-64"),
    ("41",  "PyPy 3-64"),
    ("70",  "PyPy 3-64 (PyPy 7.3.15, Python 3.10)"),
    ("87",  "PyPy 3-64 (PyPy 7.3.17, Python 3.11)"),
    ("83",  "Java 21 (64 bit)"),
    ("36",  "Java 8"),
    ("48",  "Kotlin 1.9"),
    ("88",  "Kotlin 2.1"),
    ("67",  "Ruby 3"),
    ("75",  "Rust 1.75.0 (64 bit)"),
    ("65",  "C# 8, .NET Core 3.1"),
    ("79",  "C# 10, .NET SDK 6.0"),
    ("9",   "C# Mono 6.8"),
    ("55",  "JavaScript V8 4.8.0"),
    ("34",  "JavaScript Node.js 15.8.0 (64 bit)"),
    ("61",  "Go 1.19.5"),
    ("32",  "Go 1.22.2"),
    ("12",  "Haskell GHC 8.10.1"),
    ("60",  "Scala 2.12"),
    ("77",  "Perl 5.20.1"),
    ("6",   "PHP 8.1"),
    ("72",  "Zig 0.13.0 (64 bit)"),
]

# Lookup: id -> display name
CF_LANG_BY_ID = {lid: name for lid, name in CF_LANGUAGES}

# Default language ID per file extension (used as fallback)
DEFAULT_LANG_ID_BY_EXT = {
    "cpp": "89",   # GNU G++20 13.2 (64 bit)
    "c": "43",     # GNU GCC C11
    "py": "31",    # Python 3
    "java": "83",  # Java 21
    "kt": "88",    # Kotlin 2.1
    "rs": "75",    # Rust
    "go": "32",    # Go
    "js": "34",    # Node.js
    "rb": "67",    # Ruby
    "zig": "72",   # Zig
}

SUBMIT_PAGE = "https://codeforces.com/problemset/submit"

# JavaScript: fill the problemset submit form and submit
FILL_SUBMIT_JS = r"""(function() {
    try {
        var code = atob('__CODE_B64__');

        // Fill problem code (e.g. "2181H")
        var probInput = document.querySelector('input[name="submittedProblemCode"]');
        if (probInput) {
            probInput.value = '__PROBLEM_CODE__';
            probInput.dispatchEvent(new Event('input', {bubbles: true}));
        }

        // Fill the hidden textarea
        var ta = document.getElementById('sourceCodeTextarea');
        if (ta) ta.value = code;

        // Fill the Ace editor if present
        try {
            var ed = document.querySelector('.ace_editor');
            if (ed && typeof ace !== 'undefined') ace.edit(ed).setValue(code, -1);
        } catch(e) {}

        // Select language
        var sel = document.querySelector('select[name="programTypeId"]');
        if (sel) {
            for (var i = 0; i < sel.options.length; i++) {
                if (sel.options[i].value === '__LANG_ID__') {
                    sel.value = '__LANG_ID__';
                    break;
                }
            }
            sel.dispatchEvent(new Event('change', {bubbles: true}));
        }

        // Submit the form
        var form = document.getElementById('submitForm');
        if (!form) {
            var forms = document.querySelectorAll('form');
            for (var i = 0; i < forms.length; i++) {
                var a = forms[i].getAttribute('action') || '';
                if (a.indexOf('submit') > -1) { form = forms[i]; break; }
            }
        }
        if (form) { form.submit(); return 'SUBMITTED'; }

        var btn = document.querySelector('input[type="submit"], button[type="submit"]');
        if (btn) { btn.click(); return 'SUBMITTED'; }

        return 'ERROR: Form not found. Title: ' + document.title;
    } catch(e) { return 'ERROR: ' + e.message; }
})();"""

# JavaScript: read result after redirect (returns PENDING for non-final verdicts)
READ_RESULT_JS = r"""(function() {
    try {
        var url = document.location.href;

        // Check for form validation errors (rejected before even submitting)
        var e1 = document.querySelector('.error.for__source, .error.for__submittedProblemCode');
        if (e1) return 'REJECTED: ' + e1.textContent.trim();
        var es = document.querySelectorAll('span.error');
        for (var i = 0; i < es.length; i++) {
            var t = es[i].textContent.trim();
            if (t.length > 0 && t.length < 300) return 'ERROR: ' + t;
        }

        // Look for submission rows on ANY page (status, my, or even submit page after redirect)
        var rows = document.querySelectorAll('tr[data-submission-id]');
        if (rows.length > 0) {
            var id = rows[0].getAttribute('data-submission-id');
            var cell = rows[0].querySelector('td.status-verdict-cell, td:nth-child(6), .submissionVerdictWrapper, .verdict-waiting, .verdict-accepted, .verdict-rejected');
            var vt = '';
            if (cell) {
                vt = cell.textContent.replace(/\s+/g, ' ').trim();
            }
            if (!vt) {
                // Try broader search within the row
                var spans = rows[0].querySelectorAll('span');
                for (var i = 0; i < spans.length; i++) {
                    var cls = spans[i].className || '';
                    if (cls.indexOf('verdict') > -1 || cls.indexOf('Verdict') > -1) {
                        vt = spans[i].textContent.replace(/\s+/g, ' ').trim();
                        break;
                    }
                }
            }
            if (!vt || vt.indexOf('Running') > -1 || vt.indexOf('queue') > -1 || vt.indexOf('Judging') > -1 || vt.indexOf('testing') > -1 || vt.indexOf('In queue') > -1) {
                return 'PENDING: #' + id + ' - ' + (vt || 'In queue');
            }
            return 'RESULT: #' + id + ' - ' + vt;
        }

        // If we're on a page with /my or /status but no rows found yet
        if (url.indexOf('/my') > -1 || url.indexOf('/status') > -1 || url.indexOf('/submissions') > -1) {
            return 'PENDING: Waiting for submission to appear';
        }

        // Still on submit page with no rows - possibly the form didn't actually submit
        if (url.indexOf('/submit') > -1) {
            // Check if there's a success message
            var body = document.body ? document.body.textContent : '';
            if (body.indexOf('has been submitted') > -1 || body.indexOf('submitted successfully') > -1) {
                return 'PENDING: Submitted, waiting for redirect';
            }
            return 'UNKNOWN: Still on submit page - ' + url;
        }

        return 'UNKNOWN: ' + url;
    } catch(e) { return 'ERROR: ' + e.message; }
})();"""

APPLESCRIPT = r"""tell application "System Events"
    set frontAppName to name of first application process whose frontmost is true
end tell
tell application "Safari"
    if (count of windows) is 0 then
        make new document with properties {URL:"about:blank"}
        delay 1
    end if
    tell window 1
        set submitTab to make new tab with properties {URL:"__SUBMIT_URL__"}
    end tell
    log "Loading submit page..."
    repeat 60 times
        delay 1
        try
            set formCheck to (do JavaScript "document.querySelector('select[name=\"programTypeId\"]') ? 'READY' : 'WAITING'" in submitTab)
            if formCheck is "READY" then exit repeat
        on error errMsg
            if errMsg contains "not allowed" then
                log "ERROR: Enable 'Allow JavaScript from Apple Events' in Safari > Develop menu"
                close submitTab
                tell application frontAppName to activate
                return "ERROR: Safari JavaScript from Apple Events not enabled"
            end if
        end try
    end repeat
    delay 0.5
    log "Filling form and submitting..."
    set fillJS to read POSIX file "/tmp/foc_fill_submit.js"
    set submitResult to do JavaScript fillJS in submitTab
    if submitResult does not start with "SUBMITTED" then
        log submitResult
        close submitTab
        tell application frontAppName to activate
        return submitResult
    end if
    log "Submitted! Waiting for result..."

    -- Wait for page to load after form submit (redirect)
    delay 4
    repeat 20 times
        delay 0.5
        try
            if (do JavaScript "document.readyState" in submitTab) is "complete" then exit repeat
        end try
    end repeat

    -- Poll for verdict: every 3s, up to 2 minutes (40 iterations)
    set resultJS to read POSIX file "/tmp/foc_read_result.js"
    set resultInfo to "UNKNOWN: Timed out waiting for verdict"
    repeat 40 times
        try
            set resultInfo to do JavaScript resultJS in submitTab
        on error
            set resultInfo to "PENDING: page loading..."
        end try
        log resultInfo

        -- Stop if we got a final result (not PENDING and not UNKNOWN)
        if resultInfo starts with "RESULT:" then
            exit repeat
        end if
        if resultInfo starts with "REJECTED:" then
            exit repeat
        end if
        if resultInfo starts with "ERROR:" then
            exit repeat
        end if

        -- For UNKNOWN on submit page, try reloading to the my-submissions page
        if resultInfo starts with "UNKNOWN: Still on submit page" then
            log "Redirecting to submissions page..."
            do JavaScript "window.location.href = 'https://codeforces.com/my'" in submitTab
            delay 4
            repeat 15 times
                delay 0.5
                try
                    if (do JavaScript "document.readyState" in submitTab) is "complete" then exit repeat
                end try
            end repeat
        end if

        delay 3
        -- Reload to get fresh verdict
        try
            do JavaScript "window.location.reload()" in submitTab
        end try
        delay 2
        repeat 15 times
            delay 0.5
            try
                if (do JavaScript "document.readyState" in submitTab) is "complete" then exit repeat
            end try
        end repeat
    end repeat

    close submitTab
end tell
delay 0.3
tell application frontAppName to activate
return resultInfo"""


class FocSubmitSolutionCommand(sublime_plugin.TextCommand):
    """Submits the current solution to Codeforces via background Safari."""

    def run(self, edit):
        view = self.view
        window = view.window()
        file_path = view.file_name()

        if not file_path:
            sublime.error_message("FOC Submit: No file is open.")
            return

        meta_path = get_meta_file_path(file_path)
        if not os.path.exists(meta_path):
            sublime.error_message(
                "FOC Submit: No problem URL found.\n\n"
                "This file was not parsed from Competitive Companion."
            )
            return

        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.loads(f.read())
        except Exception as e:
            sublime.error_message("FOC Submit: Bad metadata.\n\n{}".format(e))
            return

        url = meta.get("url", "")
        if not url:
            sublime.error_message("FOC Submit: No URL in metadata.")
            return

        # Extract problem code from URL (e.g. "2181H")
        problem_code = self._extract_problem_code(url)
        if not problem_code:
            sublime.error_message(
                "FOC Submit: Could not parse problem code from URL:\n{}".format(url)
            )
            return

        # Resolve language
        lang_id, lang_name = self._get_language(file_path)

        test_status_line = self._get_test_status(window, file_path)
        confirm_msg = "Submit:   {}\nProblem:  {}\nLang:     {} ({})\nURL:      {}".format(
            os.path.basename(file_path), problem_code, lang_name, lang_id, url
        )
        if test_status_line:
            confirm_msg += "\n\n{}".format(test_status_line)
        if not sublime.ok_cancel_dialog(confirm_msg, "Submit"):
            return

        if view.is_dirty():
            view.run_command("save")

        self._do_submit(window, url, file_path, meta, problem_code, lang_id, lang_name)

    def _extract_problem_code(self, url):
        """
        Extract problem code from Codeforces URL.
        /problemset/problem/2181/H  → '2181H'
        /contest/2181/problem/H     → '2181H'
        /gym/100001/problem/A       → '100001A'
        """
        # /problemset/problem/{id}/{letter}
        m = re.search(r"/problemset/problem/(\d+)/(\w+)", url)
        if m:
            return "{}{}".format(m.group(1), m.group(2))

        # /contest/{id}/problem/{letter}  or  /gym/{id}/problem/{letter}
        m = re.search(r"/(?:contest|gym)/(\d+)/problem/(\w+)", url)
        if m:
            return "{}{}".format(m.group(1), m.group(2))

        return None

    def _get_test_status(self, window, file_path):
        opd_view = next(
            (v for v in window.views() if v.settings().get("is_opd_view")), None
        )
        if not opd_view:
            return "WARNING: Tests have not been run."
        results = opd_view.settings().get("foc_test_results")
        if not results:
            return "WARNING: Tests have not been run yet."
        results_file = results.get("run_file", "")
        if results_file and os.path.basename(results_file) != os.path.basename(file_path):
            return "WARNING: Results are for a different file ({}).".format(
                os.path.basename(results_file)
            )
        total = results.get("total", 0)
        passed = results.get("passed", 0)
        failed = results.get("failed", 0)
        error = results.get("error", 0)
        not_run = results.get("not_run", 0)
        if total == 0:
            return "WARNING: No test cases."
        if not results.get("complete", False):
            return "WARNING: Tests still running."
        if not_run > 0:
            return "WARNING: {}/{} tests not run.".format(not_run, total)
        if passed == total:
            return "All {}/{} tests passed.".format(passed, total)
        parts = []
        if passed:
            parts.append("{} passed".format(passed))
        if failed:
            parts.append("{} FAILED".format(failed))
        if error:
            parts.append("{} errors".format(error))
        return "WARNING: {}/{} tests OK ({}). Submit anyway?".format(
            passed, total, ", ".join(parts)
        )

    def _get_language(self, file_path):
        """Return (lang_id, lang_name) based on stored setting or file extension fallback."""
        settings = get_settings()
        stored_id = settings.get("cf_selected_language_id", "")
        if stored_id and stored_id in CF_LANG_BY_ID:
            return str(stored_id), CF_LANG_BY_ID[stored_id]

        # Fallback: pick from extension
        ext = os.path.splitext(file_path)[1][1:]
        fallback_id = str(DEFAULT_LANG_ID_BY_EXT.get(ext, "89"))
        return fallback_id, CF_LANG_BY_ID.get(fallback_id, "Unknown")

    def _do_submit(self, window, url, file_path, meta, problem_code, lang_id, lang_name):
        panel = window.create_output_panel("foc_submit")
        panel.settings().set("word_wrap", True)
        panel.settings().set("gutter", False)
        panel.settings().set("line_numbers", False)
        window.run_command("show_panel", {"panel": "output.foc_submit"})

        # Read source code
        with open(file_path, "r", encoding="utf-8") as f:
            source_code = f.read()
        code_b64 = base64.b64encode(source_code.encode("utf-8")).decode("ascii")

        # Write temp JS files
        fill_js = (
            FILL_SUBMIT_JS
            .replace("__CODE_B64__", code_b64)
            .replace("__LANG_ID__", lang_id)
            .replace("__PROBLEM_CODE__", problem_code)
        )
        with open("/tmp/foc_fill_submit.js", "w", encoding="utf-8") as f:
            f.write(fill_js)
        with open("/tmp/foc_read_result.js", "w", encoding="utf-8") as f:
            f.write(READ_RESULT_JS)

        # Write AppleScript (always uses the generic submit page)
        ascript = APPLESCRIPT.replace("__SUBMIT_URL__", SUBMIT_PAGE)
        with open("/tmp/foc_submit.applescript", "w", encoding="utf-8") as f:
            f.write(ascript)

        # Header
        problem_name = meta.get("name", "")
        group = meta.get("group", "")
        header = "=" * 55 + "\n  FOC Submit (Safari)\n" + "=" * 55 + "\n"
        if problem_name:
            header += "  Problem:      {}\n".format(problem_name)
        if group:
            header += "  Contest:      {}\n".format(group)
        header += "  Problem Code: {}\n".format(problem_code)
        header += "  File:         {}\n".format(os.path.basename(file_path))
        header += "  Language:     {} ({})\n".format(lang_name, lang_id)
        header += "-" * 55 + "\n\n"
        self._append(panel, header)

        def run_in_thread():
            try:
                proc = subprocess.Popen(
                    ["osascript", "/tmp/foc_submit.applescript"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                )
                for line in iter(proc.stderr.readline, ""):
                    line = line.strip()
                    if line:
                        sublime.set_timeout(lambda l=line: self._append(panel, "  " + l + "\n"), 0)
                proc.stderr.close()
                proc.wait()
                result = proc.stdout.read().strip()
                proc.stdout.close()

                if result.startswith("RESULT:"):
                    verdict_text = result.split(" - ", 1)[-1].lower() if " - " in result else ""
                    if "accepted" in verdict_text:
                        footer = "\n" + "=" * 55 + "\n  ✅ ACCEPTED\n  {}\n".format(result) + "=" * 55 + "\n"
                    else:
                        footer = "\n" + "=" * 55 + "\n  ❌ {}\n  {}\n".format(verdict_text.upper().strip(), result) + "=" * 55 + "\n"
                elif result.startswith("ERROR") or result.startswith("REJECTED"):
                    footer = "\n" + "=" * 55 + "\n  SUBMISSION FAILED\n  {}\n".format(result) + "=" * 55 + "\n"
                else:
                    footer = "\n" + "=" * 55 + "\n  {}\n".format(result) + "=" * 55 + "\n"

                sublime.set_timeout(lambda: self._append(panel, footer), 0)
                sublime.set_timeout(
                    lambda: sublime.status_message("FOC: {}".format(result[:60])), 0
                )
            except Exception as e:
                sublime.set_timeout(
                    lambda: self._append(panel, "\nERROR: {}\n".format(e)), 0
                )
            finally:
                for p in ["/tmp/foc_fill_submit.js", "/tmp/foc_read_result.js", "/tmp/foc_submit.applescript"]:
                    try:
                        os.remove(p)
                    except OSError:
                        pass

        threading.Thread(target=run_in_thread, daemon=True).start()

    def _append(self, panel, text):
        panel.run_command("append", {"characters": text, "scroll_to_end": True})


class FocSelectLanguageCommand(sublime_plugin.WindowCommand):
    """Lets the user pick a Codeforces language. Persists across sessions."""

    def run(self):
        settings = get_settings()
        current_id = settings.get("cf_selected_language_id", "")

        items = []
        selected_index = 0
        for i, (lid, name) in enumerate(CF_LANGUAGES):
            marker = "  >> " if lid == current_id else "     "
            items.append("{}{} (ID {})".format(marker, name, lid))
            if lid == current_id:
                selected_index = i

        def on_done(idx):
            if idx < 0:
                return
            chosen_id, chosen_name = CF_LANGUAGES[idx]
            settings.set("cf_selected_language_id", chosen_id)
            sublime.save_settings("FastOlympicCoding.sublime-settings")
            sublime.status_message("FOC: Language set to {} ({})".format(chosen_name, chosen_id))

        self.window.show_quick_panel(items, on_done, selected_index=selected_index)

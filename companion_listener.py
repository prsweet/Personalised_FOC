import sublime
import sublime_plugin
import socketserver
import http.server
import threading
import json
import os
from os import path
import re
import subprocess
import time

from .settings import get_settings, get_tests_file_path

# --- Global variables to manage the server thread ---
SERVER_THREAD = None
HTTP_SERVER = None

class CompanionHandler(http.server.SimpleHTTPRequestHandler):
    """
    Handles POST requests from the Competitive Companion browser extension.
    """
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        try:
            data = json.loads(body.decode('utf-8'))
            # Pass data to a Sublime Text command to handle it safely in the main thread
            sublime.active_window().run_command('foc_parse_problem', {'data': data})
        except Exception as e:
            print("[FastOlympicCoding Companion] Error parsing data: {}".format(e))

        self.send_response(200)
        self.end_headers()

    # Suppress log messages to the console for every request
    def log_message(self, format, *args):
        return

def force_kill_process_on_port(port):
    """Finds and kills any process listening on the given port."""
    if sublime.platform() != 'osx' and sublime.platform() != 'linux':
        # This implementation is for macOS/Linux. A different command would be needed for Windows.
        return

    try:
        # The command `lsof -t -i:PORT` returns just the PID of the process using the port
        command = "lsof -t -i:{}".format(port)
        
        # Use Popen to run the command
        proc = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()
        
        if proc.returncode == 0:
            pid = stdout.decode('utf-8').strip()
            if pid:
                print("[FastOlympicCoding Companion] Port {} is in use by PID {}. Attempting to kill.".format(port, pid))
                kill_command = "kill -9 {}".format(pid)
                subprocess.Popen(kill_command, shell=True).wait()
                time.sleep(0.1) # Give the OS a moment to release the port
                print("[FastOlympicCoding Companion] Process {} killed.".format(pid))
    except Exception as e:
        print("[FastOlympicCoding Companion] Error trying to kill process on port {}: {}".format(port, e))


def start_server():
    """Starts the HTTP server in a background thread."""
    global SERVER_THREAD, HTTP_SERVER
    
    # Ensure we don't start multiple servers
    if SERVER_THREAD and SERVER_THREAD.is_alive():
        return
    
    port = get_settings().get('companion_listener_port', 10043)
    
    # --- NEW: Automatically kill existing process ---
    force_kill_process_on_port(port)

    try:
        HTTP_SERVER = socketserver.TCPServer(("", port), CompanionHandler)
        
        SERVER_THREAD = threading.Thread(target=HTTP_SERVER.serve_forever)
        SERVER_THREAD.daemon = True
        SERVER_THREAD.start()
        print("[FastOlympicCoding Companion] Server started on port {}".format(port))
    except Exception as e:
        print("[FastOlympicCoding Companion] Failed to start server: {}".format(e))
        sublime.status_message("FOC: Failed to start Companion listener on port {}".format(port))

def stop_server():
    """Stops the HTTP server."""
    global HTTP_SERVER
    if HTTP_SERVER:
        HTTP_SERVER.shutdown()
        HTTP_SERVER.server_close()
        print("[FastOlympicCoding Companion] Server stopped.")

class FocParseProblemCommand(sublime_plugin.WindowCommand):
    """
    A Sublime command that takes problem data and sets up the files and tests.
    """
    def run(self, data):
        try:
            problem_name = data.get('name', 'problem')
            
            # Sanitize the problem name to create a safe filename.
            # "F. Minimum Adjacent Swaps" -> "F_Minimum_Adjacent_Swaps"
            safe_filename = problem_name.replace(' ', '_')
            safe_filename = safe_filename.replace('.', '_', 1)
            # Remove any other characters that aren't letters, numbers, or underscores
            safe_filename = re.sub(r'[^\w_]', '', safe_filename)

            lang_ext = get_settings().get('default_language_extension', 'cpp')
            file_name = "{}.{}".format(safe_filename, lang_ext)
            
            # Determine the active folder, or default to user's home
            active_folder = self.get_active_folder()
            if not active_folder:
                print("[FastOlympicCoding Companion] Could not determine a valid folder to create files in.")
                sublime.status_message("FOC Error: No active folder found.")
                return

            file_path = path.join(active_folder, file_name)

            # 1. Create the source file if it doesn't exist
            if not path.exists(file_path):
                template_path = get_settings().get('cpp_template_path')
                template_content = ''

                # Check if template_path is set and exists
                if template_path:
                    # Sublime's API is the most reliable way to read a package resource
                    try:
                        template_content = sublime.load_resource(template_path)
                    except Exception as e:
                        print("[FastOlympicCoding Companion] Error reading template file '{}': {}".format(template_path, e))
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(template_content)

            # 2. Format and write the test cases to the corresponding tests file
            tests_to_write = []
            for test in data.get('tests', []):
                tests_to_write.append({
                    'test': test.get('input', '').replace('\r\n', '\n'),
                    'correct_answers': [test.get('output', '').replace('\r\n', '\n')]
                })
            
            tests_file = get_tests_file_path(file_path)
            with open(tests_file, 'w', encoding='utf-8') as f:
                f.write(sublime.encode_value(tests_to_write, True))

            # 3. Open the file and the test panel
            source_view = self.window.open_file(file_path)
            sublime.set_timeout(lambda: self.open_test_panel(source_view), 200)

        except Exception as e:
            print("[FastOlympicCoding Companion] Error processing problem: {}".format(e))
            sublime.status_message("FOC: Error processing problem.")

    def get_active_folder(self):
        # This function is now more robust
        window = sublime.active_window()
        if not window:
            return None

        # Best case: A folder is open in the sidebar
        if window.folders():
            return window.folders()[0]
        
        # Second best: The currently active file's directory
        view = window.active_view()
        if view and view.file_name():
            return path.dirname(view.file_name())
        
        # Fallback: User's home directory
        return path.expanduser('~')
            
    def open_test_panel(self, source_view):
        if source_view.is_loading():
            sublime.set_timeout(lambda: self.open_test_panel(source_view), 100)
            return
        
        self.window.focus_view(source_view)
        source_view.run_command('view_tester', {'action': 'make_opd'})

# --- Plugin lifecycle hooks ---

def plugin_loaded():
    # Load settings and start server if enabled
    def load():
        settings = sublime.load_settings("FastOlympicCoding.sublime-settings")
        if settings.get("companion_listener_enabled", True):
            start_server()
        settings.add_on_change("companion_listener_enabled", lambda: start_server() if settings.get("companion_listener_enabled") else stop_server())
    
    sublime.set_timeout(load, 2000)

def plugin_unloaded():
    stop_server()
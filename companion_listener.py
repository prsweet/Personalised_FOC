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
import signal # Added for a more robust process kill
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
            sublime.active_window().run_command('foc_parse_problem', {'data': data})
        except Exception as e:
            print("[FastOlympicCoding Companion] Error parsing data: {}".format(e))

        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        return

def force_kill_process_on_port(port):
    """
    Finds and kills any process listening on the given port.
    This version is more robust for macOS and Linux.
    """
    if sublime.platform() not in ('osx', 'linux'):
        # A different implementation would be needed for Windows
        return
    
    command = "lsof -ti tcp:{}".format(port)
    try:
        pid = subprocess.check_output(command, shell=True).decode().strip()
        if pid:
            print("[FastOlympicCoding Companion] Port {} is in use by PID {}. Attempting to kill.".format(port, pid))
            os.kill(int(pid), signal.SIGKILL)
            time.sleep(0.1) # Give the OS a moment to release the port
            print("[FastOlympicCoding Companion] Process {} killed.".format(pid))
    except subprocess.CalledProcessError:
        # This is expected if the port is not in use
        pass
    except Exception as e:
        print("[FastOlympicCoding Companion] Error trying to kill process on port {}: {}".format(port, e))


def start_server():
    """Starts the HTTP server in a background thread."""
    global SERVER_THREAD, HTTP_SERVER
    
    if SERVER_THREAD and SERVER_THREAD.is_alive():
        return
    
    port = get_settings().get('companion_listener_port', 10043)
    
    # --- Automatically kill existing process ---
    force_kill_process_on_port(port)

    try:
        # Allow the port to be reused immediately
        socketserver.TCPServer.allow_reuse_address = True
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

# ... (keep the rest of the file as is) ...

# ... (keep the rest of the file as is) ...

class FocParseProblemCommand(sublime_plugin.WindowCommand):
    """
    A Sublime command that takes problem data and sets up the files and tests.
    """
    def run(self, data):
        try:
            problem_name = data.get('name', 'problem')
            
            safe_filename = problem_name.replace(' ', '_')
            safe_filename = safe_filename.replace('.', '_', 1)
            safe_filename = re.sub(r'[^\w_]', '', safe_filename)

            lang_ext = get_settings().get('default_language_extension', 'cpp')
            file_name = "{}.{}".format(safe_filename, lang_ext)
            
            active_folder = self.get_active_folder()
            if not active_folder:
                print("[FastOlympicCoding Companion] Could not determine a valid folder to create files in.")
                sublime.status_message("FOC Error: No active folder found.")
                return

            file_path = path.join(active_folder, file_name)

            # --- UPDATED LOGIC START ---
            
            if not path.exists(file_path) and lang_ext == 'cpp':
                template_content = ''  # Default to empty content
                # Define the path to the template within the package
                template_resource_path = "Packages/CppFastOlympicCoding/my_template.cpp"

                try:
                    # Load the template file using Sublime's API
                    template_content = sublime.load_resource(template_resource_path)
                except Exception as e:
                    print("[FastOlympicCoding Companion] Could not load template '{}'. Creating a blank file. Error: {}".format(template_resource_path, e))
                
                # Write the template content (or blank content) to the new file
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(template_content)

            # --- UPDATED LOGIC END ---

            # Always write the test cases received from Companion
            tests_to_write = []
            for test in data.get('tests', []):
                tests_to_write.append({
                    'test': test.get('input', '').replace('\r\n', '\n'),
                    'correct_answers': [test.get('output', '').replace('\r\n', '\n')]
                })
            
            tests_file = get_tests_file_path(file_path)
            with open(tests_file, 'w', encoding='utf-8') as f:
                f.write(sublime.encode_value(tests_to_write, True))

            source_view = self.window.open_file(file_path)
            sublime.set_timeout(lambda: self.open_test_panel(source_view), 100)

        except Exception as e:
            print("[FastOlympicCoding Companion] Error processing problem: {}".format(e))
            sublime.status_message("FOC: Error processing problem.")

    def get_active_folder(self):
        window = sublime.active_window()
        if not window:
            return None
        if window.folders():
            return window.folders()[0]
        view = window.active_view()
        if view and view.file_name():
            return path.dirname(view.file_name())
        return path.expanduser('~')
            
    def open_test_panel(self, source_view):
        if source_view.is_loading():
            sublime.set_timeout(lambda: self.open_test_panel(source_view), 100)
            return
        
        self.window.focus_view(source_view)
        source_view.run_command('view_tester', {'action': 'make_opd'})

# ... (keep the rest of the file as is) ...

# --- Plugin lifecycle hooks ---

def plugin_loaded():
    def load():
        settings = sublime.load_settings("FastOlympicCoding.sublime-settings")
        if settings.get("companion_listener_enabled", True):
            start_server()
        settings.add_on_change("companion_listener_enabled", lambda: start_server() if settings.get("companion_listener_enabled") else stop_server())
    
    sublime.set_timeout(load, 2000)

def plugin_unloaded():
    stop_server()

class FocReloadCompanionCommand(sublime_plugin.WindowCommand):
    """
    Reloads the FastOlympicCoding Companion plugin and restarts the listener.
    """
    def run(self):
        try:
            print("[FastOlympicCoding Companion] Reloading plugin...")
            stop_server()  # Stop current server if running
            
            # Reload the plugin package itself
            package_name = "CppFastOlympicCoding"
            sublime_plugin.reload_plugin("{}.companion_listener".format(package_name))
            
            # Give Sublime a bit of time to reload properly
            sublime.set_timeout_async(lambda: start_server(), 1000)
            
            sublime.status_message("FOC: Companion reloaded successfully.")
            print("[FastOlympicCoding Companion] Reload complete.")
        except Exception as e:
            print("[FastOlympicCoding Companion] Reload failed: {}".format(e))
            sublime.status_message("FOC: Reload failed. Check console.")
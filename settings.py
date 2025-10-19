import sublime
import os

# --- Your existing code (restored) ---
root_dir = os.path.split(__file__)[0]
base_name = os.path.split(root_dir)[1]
settings_file = 'FastOlympicCoding.sublime-settings'
default_settings_file = 'FastOlympicCoding ({os}).sublime-settings'.format(
    os={ 'windows': 'Windows', 'linux': 'Linux', 'osx': 'OSX' }[sublime.platform().lower()]
)
tests_file_suffix = ':tests'
tests_relative_dir = ''
settings = {}
run_supported_exts = set()

def get_settings():
    return settings

def init_settings(_settings):
    global settings
    settings = _settings

def is_run_supported_ext(ext):
    _run_settings = get_settings().get('run_settings', None)
    if _run_settings is not None:
        for option in _run_settings:
            if ext in option['extensions']:
                return True
    return False

def get_supported_exts(lang):
    _run_settings = get_settings().get('run_settings', None)
    if _run_settings is not None:
        for option in _run_settings:
            if option['name'] == lang:
                return option['extensions']
        return []
    return []

def is_lang_view(view, lang):
    if view.file_name() is None: return False
    return os.path.splitext(view.file_name())[1][1:] in get_supported_exts(lang)

def try_load_settings():
    _settings = sublime.load_settings(settings_file)
    if _settings is None:
        # Assuming load_settings is a custom function or typo for sublime.load_settings
        sublime.set_timeout_async(lambda: init_settings(sublime.load_settings(settings_file)), 200)
    else:
        init_settings(_settings)
        sublime.status_message('FastOlympicCoding: settings loaded')

def plugin_loaded():
    sublime.set_timeout(try_load_settings, 200)

def get_tests_file_suffix():
    return get_settings().get('tests_file_suffix') or tests_file_suffix

# --- NEW MERGED FUNCTIONS START ---

def get_project_folder():
    """Finds the first open folder in the window, which is the project root."""
    window = sublime.active_window()
    if window and window.folders():
        return window.folders()[0]
    view = window.active_view()
    if view and view.file_name():
        return os.path.dirname(view.file_name())
    return None

def get_hidden_folder_path(folder_name):
    """Ensures a hidden folder (e.g., .TestCases) exists and returns its path."""
    project_folder = get_project_folder()
    if not project_folder:
        return None
    
    hidden_folder_path = os.path.join(project_folder, folder_name)
    os.makedirs(hidden_folder_path, exist_ok=True)
    return hidden_folder_path

def get_tests_file_path(source_file):
    """
    Returns the path for the .tests file inside the .TestCases directory.
    This replaces your original function.
    """
    test_cases_dir = get_hidden_folder_path('.TestCases')
    if not test_cases_dir:
        # Fallback to old behavior if no project folder is found
        return source_file + get_tests_file_suffix()
    
    base_name = os.path.basename(source_file)
    return os.path.join(test_cases_dir, base_name + get_tests_file_suffix())

def get_binary_path(source_file):
    """
    Returns the path for the compiled binary inside the .Compiled directory.
    """
    compiled_dir = get_hidden_folder_path('.Compiled')
    if not compiled_dir:
        # Fallback to compiling in the same directory
        return os.path.splitext(source_file)[0]
        
    file_name_without_ext = os.path.basename(os.path.splitext(source_file)[0])
    return os.path.join(compiled_dir, file_name_without_ext)

# --- NEW MERGED FUNCTIONS END ---
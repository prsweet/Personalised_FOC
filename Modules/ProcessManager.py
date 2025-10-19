from os.path import dirname, split, splitext
from os import path, setsid
import os
import subprocess
import signal
import sublime
from ..settings import get_binary_path 

class ProcessManager(object):
    def __init__(self, file, syntax, run_settings=None):
        self.syntax = syntax
        self.file = file
        self.is_run = False
        self.test_counter = 0
        self.write = self.insert
        self.run = self.run_file
        self.run_settings = run_settings
        self.file_name = splitext(split(file)[1])[0]
        self.binary_path = get_binary_path(file)

    def format_command(self, cmd, args=''):
        file = split(self.file)[1]
        return cmd.format(
            file=file,
            source_file=self.file,
            source_file_dir=path.dirname(self.file),
            file_name=self.file_name,
            binary_path=self.binary_path,
            args=args
        )

    def get_compile_cmd(self):
        ext = splitext(self.file)[1][1:]
        for x in self.run_settings:
            if ext in x['extensions']:
                if x['compile_cmd'] is None:
                    return None
                cmd_template = x['compile_cmd'].replace(self.file_name, '{binary_path}')
                return self.format_command(cmd_template)
        return -1

    def get_run_cmd(self, args):
        ext = splitext(self.file)[1][1:]
        for x in self.run_settings:
            if ext in x['extensions']:
                if x['run_cmd'] is None:
                    return None
                cmd_template = x['run_cmd'].replace('./"{file_name}"', '"{binary_path}"')
                cmd_template = cmd_template.replace('"{file_name}"', '"{binary_path}"')
                return self.format_command(cmd_template, args=args)
        return -1

    def compile(self, wait_close=True):
        cmd = self.get_compile_cmd()
        if cmd:
            p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 cwd=path.dirname(self.binary_path))
            out = p.communicate()[0].decode('utf-8', 'ignore')
            return (p.returncode, out)

    def run_file(self, args=[]):
        cmd = self.get_run_cmd(' '.join(args))
        self.is_run = True
        if sublime.platform() == 'windows':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            preexec_fn = None
            use_shell = False
        else:
            startupinfo = None
            preexec_fn = os.setsid
            use_shell = True

        self.process = subprocess.Popen(
            cmd,
            shell=use_shell,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            cwd=path.dirname(self.binary_path),
            startupinfo=startupinfo,
            preexec_fn=preexec_fn,
            universal_newlines=True
        )

    def insert(self, s):
        if self.process.poll() is None:
            try:
                if s and not s.endswith('\n'):
                    s += '\n'
                self.process.stdin.write(s)
                self.process.stdin.flush()
            except (IOError, BrokenPipeError):
                pass

    def finish_input(self):
        try:
            self.process.stdin.close()
        except Exception:
            pass

    def read(self, bfsize=None):
        if bfsize is None:
            return self.process.stdout.read()
        else:
            return self.process.stdout.read(bfsize)

    def is_stopped(self):
        return self.process.poll()

    def terminate(self):
        if self.process.poll() is not None: return
        if sublime.platform() == 'linux':
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            self.process.kill()
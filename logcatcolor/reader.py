"""
logcat-color

Copyright 2012, Marshall Culpepper
Licensed under the Apache License, Version 2.0

Logcat I/O stream readers and helpers
"""
from __future__ import unicode_literals
import asyncore
import asynchat
from io import StringIO
import fcntl
from logcatcolor.format import BriefFormat, Format, detect_format
from logcatcolor.layout import BriefLayout, Layout
import os
import sys
import traceback

# Parts copied from asyncore.file_dispatcher
class FileLineReader(asynchat.async_chat):
    LINE_TERMINATOR = b"\n"

    def __init__(self, fd):
        asynchat.async_chat.__init__(self)
        self.connected = True
        self.log_buffer = StringIO()

        self.set_file(fd)
        self.set_terminator(self.LINE_TERMINATOR)

    def set_file(self, fd):
        try:
            # fd may be a file object
            fd = fd.fileno()
        except AttributeError:
            pass

        self.socket = asyncore.file_wrapper(fd)
        self._fileno = self.socket.fileno()
        self.add_channel()

        flags = fcntl.fcntl(fd, fcntl.F_GETFL, 0)
        flags = flags | os.O_NONBLOCK
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)

    def collect_incoming_data(self, data):
        # some logcat message may not be valid UTF-8. For example, Magisk Manager after
        # hiding uses title Manager\xc0\x80\xc0\x80\xc0\x80\xc0\x80\xc0\x80\xc0\x80\xc0\x80
        self.log_buffer.write(data.decode('utf-8', errors='backslashreplace'))

    def found_terminator(self):
        line = self.log_buffer.getvalue()
        try:
            self.process_line(line)
        except:
            traceback.print_exc()
            sys.exit(1)

        self.log_buffer = StringIO()

    def process_line(self):
        pass

class LogcatReader(FileLineReader):
    DETECT_COUNT = 3

    def __init__(self, file, config, profile=None, format=None, layout=None,
                 writer=None, width=80):
        FileLineReader.__init__(self, file)
        self.detect_lines = []
        self.config = config
        self.profile = profile
        self.width = width
        self.writer = writer or sys.stdout
        try:
            self.writer = self.writer.buffer
        except AttributeError:
            pass

        self.format = None
        if format is not None:
            FormatType = Format.TYPES[format]
            self.format = FormatType()

        self.layout = None
        if layout is not None:
            LayoutType = Layout.TYPES[layout]
            self.layout = LayoutType(config, profile, width)

    def __del__(self):
        # Clear the "detect" lines if we weren't able to detect a format
        if len(self.detect_lines) > 0 and not self.format:
            self.format = BriefFormat()
            if not self.layout:
                self.layout = BriefLayout(self.config)

            for line in self.detect_lines:
                self.layout_line(line)

    def detect_format(self, line):
        if len(self.detect_lines) < self.DETECT_COUNT:
            self.detect_lines.append(line)
            return False

        format_name = detect_format(self.detect_lines) or "brief"
        self.format = Format.TYPES[format_name]()
        if not self.layout:
            self.layout = Layout.TYPES[format_name](self.config, self.profile,
                self.width)

        for line in self.detect_lines:
            self.layout_line(line)

        self.detect_lines = []
        return True

    def process_line(self, line):
        line = line.strip()
        if not self.format:
            if not self.detect_format(line):
                return

        self.layout_line(line)

    def layout_line(self, line):
        if Format.MARKER_REGEX.match(line):
            result = self.layout.layout_marker(line)
            if result:
                self.writer.write(result.encode('utf-8'))
            return

        try:
            if not self.format.match(line) or not self.format.include(self.profile):
                return

            result = self.layout.layout_data(self.format.data)
            if not result:
                return

            self.writer.write((result + "\n").encode('utf-8'))
        finally:
            self.format.data.clear()

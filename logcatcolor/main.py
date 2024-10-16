from __future__ import print_function, unicode_literals
"""
logcat-color

Copyright 2012, Marshall Culpepper
Licensed under the Apache License, Version 2.0

Portions Copyright 2009, The Android Open Source Project
Thanks to Jeff Sharkey, the author of coloredlogcat.py,
the original inspiration of logcat-color
"""
import asyncore
import errno
import fcntl
import optparse
import os
import struct
import sys
import termios

from colorama import Fore, Back, Style
from subprocess import check_call, Popen, PIPE

from logcatcolor.config import LogcatColorConfig
from logcatcolor.profile import Profile
from logcatcolor.reader import LogcatReader

class LogcatColor(object):
    def __init__(self, args=None):
        self.parse_args(args)
        self.width = self.get_term_width()
        self.config = LogcatColorConfig(self.options)

        self.profile = None
        if len(self.args) >= 1:
            self.profile = Profile.get_profile(self.args[0])
            if self.profile:
                self.args = self.args[1:]

        if not self.profile:
            self.logcat_args.extend(self.args)

        self.format = None
        if self.options.format:
            self.format = self.options.format
        elif self.profile and self.profile.format:
            self.format = self.profile.format

        self.layout = self.format
        if self.options.plain:
            self.layout = "raw"

        self.proc = None

    def get_term_width(self):
        out_fd = self.output.fileno()
        if os.isatty(out_fd):
            # unpack the current terminal width / height
            data = fcntl.ioctl(out_fd, termios.TIOCGWINSZ, '1234')
            height, width = struct.unpack('hh', data)
        else:
           # store a large width when the output of this script is being piped
           width = 2000

        return width

    def parse_args(self, args=None):
        parser = optparse.OptionParser()

        # logcat-color options
        parser.add_option("--config", dest="config", default=None,
            help="path to logcat-color config file (default: ~/.logcat-config)")
        parser.add_option("--plain", action="store_true",
            dest="plain", default=False,
            help="apply profiles and filters, but don't colorize / format" +
                 " output (useful for logging to a file)")
        parser.add_option("--no-wrap", action="store_false", dest="wrap",
            default=None, help="don't wrap console text into a column " +
                               "(makes for better copy/paste)")
        parser.add_option("--stay-connected", action="store_true", default=None,
            dest="stay_connected", help="keep logcat-color running when the "
                                        "device disconnects, and automatically "
                                        "wait for the device to reconnect")
        parser.add_option("-i", "--input", metavar="FILE", dest="input",
            default=None,
            help="read input from FILE, instead of starting adb. this is " +
                 "equivalent to piping FILE to logcat-color. (default: start " +
                 "adb, and read from it's stdout)")
        parser.add_option("-o", "--output", metavar="FILE", dest="output",
            default=None, help="write output to FILE (default: stdout)")

        # ADB options
        parser.add_option("-d", "--device", action="store_const",
            dest="adb_device", const="device",
            help="connect to the only plugged-in device")
        parser.add_option("-e", "--emulator", action="store_const",
            dest="adb_device", const="emulator",
            help="connect to the only running emulator")
        parser.add_option("-s", "--serial-number", dest="adb_device",
            help="connect to a specific device by it's serial number")

        # Logcat options
        # See http://developer.android.com/guide/developing/tools/logcat.html
        # We can't support -d / -s since we use them for ADB above, but we
        # provide long-form options in case they are needed
        parser.add_option("-b", "--buffer", action="append", dest="buffers",
            help="loads an alternate log buffer for viewing, such as event or" +
                 " radio")
        parser.add_option("-c", "--clear", action="append_const",
            dest="logcat_args", const="-c",
            help="clears (flushes) the entire log and exits")
        parser.add_option("--dump", action="append_const",
            dest="logcat_args", const="-d",
            help="dumps the log to the screen and exits")
        parser.add_option("-f", "--file", dest="file", default=None,
            help="writes log message output to <file>. the default is stdout")
        parser.add_option("-g", "--print-size", action="append_const",
            dest="logcat_args", const="-g",
            help="prints the size of the specified log buffer and exits")
        parser.add_option("-n", "--max-rotated-logs",
            dest="max_rotated_logs", type="int",
            help="sets the maximum number of rotated logs. requires the -r" +
                 " option (default: 4)")
        parser.add_option("-r", "--rotate", dest="rotate_kbytes", type="int",
            help="rotates the log file every <rotate_kbytes> of output." +
                 " requires the -f option (default: 16)")
        parser.add_option("--silent", action="append_const", dest="logcat_args",
            const="-s", help="sets the default filter spec to silent")
        parser.add_option("-v", "--format", dest="format", default=None,
            help="sets the output format for log messages. possible formats:" +
                 " brief, process, tag, raw, time, threadtime, long" +
                 " (default: brief)")

        (options, args) = parser.parse_args(args)
        self.options = options
        self.args = args

        if options.config and not os.path.isfile(options.config):
            parser.error("Config file does not exist: %s" % options.config)

        try:
            self.input = sys.stdin.buffer
        except AttributeError:
            self.input = sys.stdin
        if options.input:
            self.input = open(options.input, "rb")

        try:
            self.output = sys.stdout.buffer
        except AttributeError:
            self.output = sys.stdout
        if options.output:
            self.output = open(options.output, "wb")

        self.adb_device = options.adb_device
        self.logcat_args = options.logcat_args or []

        if options.buffers:
            for buf in options.buffers:
                self.logcat_args.extend(["-b", buf])

        if options.file:
            self.logcat_args.extend(["-f", options.file])

        if options.max_rotated_logs:
            self.logcat_args.extend(["-n", options.max_rotated_logs])

        if options.rotate_kbytes:
            self.logcat_args.extend(["-r", options.rotate_kbytes])

    def get_adb_args(self):
        adb = "adb" # Let the system find adb on the PATH
        if "ADB" in os.environ:
            adb = os.environ["ADB"]

        config_adb = self.config.get_adb()
        if config_adb:
            adb = config_adb

        adb_args = [adb]
        if not self.adb_device and self.profile:
            emulator = self.profile.emulator
            if emulator:
                self.adb_device = \
                    emulator if type(emulator) is str else "emulator"

            device = self.profile.device
            if device:
                self.adb_device = device if type(device) is str else "device"

        if self.adb_device == "emulator":
            adb_args.append("-e")
        elif self.adb_device == "device":
            adb_args.append("-d")
        elif self.adb_device:
            adb_args.extend(["-s", self.adb_device])

        return adb_args

    def get_logcat_args(self):
        logcat_args = self.logcat_args[:]
        if self.format:
            # put format in front in case custom filters are used
            logcat_args[0:0] = ["-v", self.format]

        if self.profile:
            buffers = self.profile.buffers
            if buffers:
                for b in buffers: logcat_args.extend(["-b", b])

        return logcat_args

    def start_logcat(self):
        adb_command = self.get_adb_args()
        adb_command.append("logcat")
        adb_command.extend(self.get_logcat_args())
        try:
            self.proc = Popen(adb_command, stdout=PIPE)
            if self.options.input:
                self.input.close()
            self.input = self.proc.stdout
        except OSError as e:
            if e.errno == errno.ENOENT:
                print(
                    'Error, adb could not be found using: "%s"\n' \
                    'To fix this: \n' \
                    '  1) Add the directory containing adb to your PATH\n' \
                    '  2) Set the ADB environment variable\n' \
                    '  3) Set "adb" in ~/.logcat-color' % adb_command[0],
                    file=sys.stderr)
            else:
                print('Could not run ADB: %s' % str(e), file=sys.stderr)
            sys.exit(e.errno)

    def init_reader(self):
        LogcatReader(self.input, self.config, profile=self.profile,
            format=self.format, layout=self.layout, writer=self.output,
            width=self.width)

    def start(self):
        # if someone is piping, use stdin as input. if not, invoke adb logcat
        if self.input.isatty():
            self.start_logcat()

        self.init_reader()

    def loop(self):
        try:
            self.start()
            while True:
                asyncore.loop()
                if not self.config.get_stay_connected():
                    break
                self.wait_for_device()
                self.start_logcat()
                self.init_reader()
                if self.proc is not None:
                    self.proc.stdout.close()
                    self.proc.wait()
        except KeyboardInterrupt:
            pass

    WAIT_FOR_DEVICE = Fore.WHITE + Back.BLACK + Style.DIM + \
                      "--- Waiting for device" + Style.RESET_ALL + \
                      Fore.BLUE + Back.BLACK + Style.DIM + " %s" +  Style.RESET_ALL + \
                      Fore.WHITE + Back.BLACK + Style.DIM + "---" + Style.RESET_ALL

    def wait_for_device(self):
        command = self.get_adb_args()
        command.append("wait-for-device")

        device_str = ""
        if self.adb_device:
            device_str = "\"%s\" " % self.adb_device

        print(self.WAIT_FOR_DEVICE % device_str)
        check_call(command)

def main():
    LogcatColor().loop()

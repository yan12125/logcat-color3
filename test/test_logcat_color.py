from __future__ import print_function, unicode_literals
import common
import json
import os
from subprocess import Popen, PIPE
import sys
import tempfile
import unittest

from common import LogcatColor, MockAdbLogcatColor
this_dir = os.path.dirname(os.path.abspath(__file__))

def logcat_color_test(*args, **kwargs):
    def run_logcat_color_test(fn):
        def wrapped(self):
            self.start_logcat_color(*args, **kwargs)
            fn(self)
        return wrapped
    return run_logcat_color_test

logs_dir = os.path.join(this_dir, "logs")
configs_dir = os.path.join(this_dir, "configs")

BRIEF_LOG = os.path.join(logs_dir, "brief_log")
NON_UTF8_LOG = os.path.join(logs_dir, "non_utf8_log")
NON_UTF8_OUTPUT = os.path.join(logs_dir, "non_utf8_output")
BRIEF_FILTER_CONFIG = os.path.join(configs_dir, "brief_filter_config")
EMPTY_CONFIG = os.path.join(configs_dir, "empty_config")

tmpfd, tmpin = tempfile.mkstemp()
os.close(tmpfd)
tmpfd, tmpout = tempfile.mkstemp()
os.close(tmpfd)

class LogcatColorTest(unittest.TestCase):
    DEBUG = False

    def setUp(self):
        # Clear out our temporary output file before each test
        global tmpout
        with open(tmpout, "w") as f: f.write("")

    def start_logcat_color(self, *args, **kwargs):
        args = list(args)
        if "config" in kwargs:
            args = ["--config", kwargs["config"]] + args
            del kwargs["config"]
        elif "--config" not in args:
            # fall back to empty config
            args = ["--config", EMPTY_CONFIG] + args

        piped = ""
        piped_path = None
        if "piped" in kwargs:
            piped_path = kwargs["piped"]
            with open(piped_path, "rb") as f:
                piped = f.read()
            del kwargs["piped"]
        elif "input" in kwargs:
            piped = None
            args = ["--input", kwargs["input"]] + args
            del kwargs["input"]

        args = [sys.executable, '-c', 'from logcatcolor.main import main; main()'] + args

        if self.DEBUG:
            piped_debug = ""
            if piped_path:
                piped_debug = " < %s" % piped_path

            print(" ".join(args) + piped_debug)

        self.proc = Popen(args, stdout=PIPE, stderr=PIPE, stdin=PIPE, **kwargs)
        self.out, self.err = self.proc.communicate(piped)
        self.out = self.out.decode('utf-8')

        self.filter_results = common.read_filter_results()
        if os.path.exists(common.filter_results):
            os.unlink(common.filter_results)

        if self.DEBUG and self.err:
            print(self.err.decode('utf-8'), file=sys.stderr)

    @logcat_color_test(piped=BRIEF_LOG)
    def test_piped_input(self):
        self.assertEqual(self.proc.returncode, 0)

    @logcat_color_test(config="/does/not/exist")
    def test_invalid_config(self):
        self.assertNotEqual(self.proc.returncode, 0)

    @logcat_color_test("--plain", input=BRIEF_LOG)
    def test_plain_logging(self):
        self.assertEqual(self.proc.returncode, 0)
        with open(BRIEF_LOG, "rt") as f:
            brief_data = f.read()
        self.assertEqual(self.out, brief_data)

    @logcat_color_test("--plain", "brief_filter_fn",
        input=BRIEF_LOG, config=BRIEF_FILTER_CONFIG)
    def test_plain_logging_with_fn_filter(self):
        self.assertEqual(self.proc.returncode, 0)
        self.assertTrue("(  123)" not in self.out)
        self.assertTrue("( 890)" not in self.out)
        self.assertTrue("( 234)" in self.out)
        self.assertTrue("( 567)" in self.out)

        filter_results = self.filter_results.get("brief_filter_fn")
        self.assertNotEqual(filter_results, None)
        self.assertEqual(len(filter_results), 4)

        for result in filter_results:
            self.assertTrue("result" in result)
            self.assertTrue("data" in result)

        def assertResult(result, value, priority, tag, pid, msg):
            self.assertTrue("result" in result)
            self.assertEqual(result["result"], value)

            data = result["data"]
            self.assertEqual(data["priority"], priority)
            self.assertEqual(data["tag"], tag)
            self.assertEqual(data["pid"], pid)
            self.assertEqual(data["message"], msg)

        assertResult(filter_results[0], False, "I", "Tag", "123", "message")
        assertResult(filter_results[1], True, "I", "Tag2", "234", "message 2")
        assertResult(filter_results[2], True, "I", "Tag3", "567", "message 3")
        assertResult(filter_results[3], False, "I", "Tag4", "890", "message 4")

    @logcat_color_test("--plain", "brief_filter_tag",
        input=BRIEF_LOG, config=BRIEF_FILTER_CONFIG)
    def test_plain_logging_with_tag_filter(self):
        self.assertEqual(self.proc.returncode, 0)
        self.assertTrue("Tag1" not in self.out)
        self.assertTrue("Tag3" not in self.out)
        self.assertTrue("Tag2" in self.out)
        self.assertTrue("Tag4" in self.out)

    @logcat_color_test("--plain", "--output", tmpout, input=BRIEF_LOG)
    def test_file_output(self):
        self.assertEqual(self.proc.returncode, 0)
        with open(BRIEF_LOG, "rt") as f:
            brief_data = f.read()
        with open(tmpout, "rt") as f:
            out_data = f.read()
        self.assertEqual(out_data, brief_data)

    @logcat_color_test("--plain", input=NON_UTF8_LOG)
    def test_non_utf8_output(self):
        self.assertEqual(self.proc.returncode, 0)
        with open(NON_UTF8_OUTPUT, "rt") as f:
            non_utf8_output = f.read()
        self.assertEqual(self.out, non_utf8_output)

    def test_logcat_options_with_filters(self):
        # Make sure logcat flags come before filter arguments
        # https://github.com/marshall/logcat-color/issues/5
        lc = LogcatColor(args=["-v", "time", "Tag1:V", "*:S", "--silent",
                               "--print-size", "--dump", "--clear"])
        self.assertEqual(lc.format, "time")

        args = lc.get_logcat_args()

        self.assertEqual(len(args), 8)

        format_index = args.index("-v")
        self.assertTrue(format_index >= 0)
        self.assertEqual(args[format_index+1], "time")
        self.assertTrue("-s" in args)
        self.assertTrue("-d" in args)
        self.assertTrue("-g" in args)
        self.assertTrue("-c" in args)

        self.assertEqual(args[-2], "Tag1:V")
        self.assertEqual(args[-1], "*:S")

    def test_stay_connected(self):
        lc = MockAdbLogcatColor(BRIEF_LOG, tmpout,
                                args=["-s", "serial123", "--stay-connected",
                                      "--config", EMPTY_CONFIG, "--input", tmpin],
                                max_wait_count=3)
        self.assertEqual(lc.config.get_stay_connected(), True)

        lc.loop()
        self.assertEqual(lc.wait_count, 3)

        with open(tmpout, "rt") as f:
            results = json.loads(f.read())
        self.assertEqual(len(results), 5)

        logcat_results = list(filter(lambda d: d["command"] == "logcat", results))
        self.assertEqual(len(logcat_results), 2)

        wait_results = list(filter(lambda d: d["command"] == "wait-for-device", results))
        self.assertEqual(len(wait_results), 3)

        for r in results:
            self.assertEqual(r["serial"], "serial123")

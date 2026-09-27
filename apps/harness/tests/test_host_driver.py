"""Failure-path coverage for the shared Host wire driver (Assistant KB-255 / feature-t2:KB-03).

These cases do not exercise any product behaviour. They prove the driver fails loudly and locatably:
a wait that expires must name what it was waiting for, how long it waited, whether the child process
is alive, what it wrote to stderr and which frames were last exchanged. Without that, a timeout in a
long suite is an untraceable _queue.Empty and the run cannot be diagnosed from its record alone.

Every case uses a stub child process with an explicitly tiny budget, so the timeout is deterministic
and takes a fraction of a second; nothing here depends on machine load.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from host_driver import Host, HostTimeout, IDLE_SECONDS, SCALE_VARIABLE, budget, scale

# A child that accepts the connection and answers nothing: the driver must time out, not hang.
SILENT = "import sys\nsys.stdin.buffer.read()\n"
# A child that writes a diagnosable line to stderr and exits at once: the driver must report EOF.
EXITS = "import sys\nsys.stderr.write('stub refused to serve\\n')\nsys.stderr.flush()\nraise SystemExit(3)\n"


class HostDriverCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hp-host-driver-")
        self.directory = Path(self.temp.name)
        (self.directory / "host-template.json").write_text(json.dumps(dict(initialize={}, scopeRef="scope:stub")))
        self.hosts = []

    def tearDown(self):
        for host in self.hosts:
            host.close()
        self.temp.cleanup()

    def stub(self, source):
        host = Host(self.directory, command=[sys.executable, "-c", source])
        self.hosts.append(host)
        return host

    def test_expired_wait_names_what_it_waited_for_and_the_live_process(self):
        """A wait that expires raises HostTimeout whose diagnosis locates the stalled exchange."""
        host = self.stub(SILENT)
        with self.assertRaises(HostTimeout) as ctx:
            host.call("runtime.initialize", dict(probe=True), timeout=0.05)
        diagnosis = ctx.exception.diagnosis
        self.assertEqual(diagnosis["awaiting"], "runtime.initialize h:1")
        self.assertEqual(diagnosis["reason"], "runtime stayed silent")
        self.assertTrue(diagnosis["processAlive"])
        self.assertIsNone(diagnosis["returncode"])
        self.assertGreaterEqual(diagnosis["waitedSeconds"], 0.0)
        self.assertLess(diagnosis["waitedSeconds"], 5.0)
        self.assertEqual(diagnosis["idleBudgetSeconds"], round(budget(0.05), 3))
        self.assertEqual(diagnosis["pendingResponses"], [])
        self.assertEqual(diagnosis["framesExchanged"], 1)
        self.assertEqual(diagnosis["recentFrames"],
                         [dict(direction="host-to-runtime", id="h:1", method="runtime.initialize")])
        self.assertEqual(diagnosis["command"][:2], [sys.executable, "-c"])
        self.assertIn("stderr", diagnosis)
        # The message alone carries the diagnosis, so a bare traceback in a long log is enough.
        self.assertIn("runtime.initialize h:1", str(ctx.exception))

    def test_bare_pump_timeout_is_also_diagnosable(self):
        """A bare pump wait expires with the same diagnosis rather than a context-free queue error."""
        host = self.stub(SILENT)
        with self.assertRaises(HostTimeout) as ctx:
            host.pump(0.05)
        self.assertEqual(ctx.exception.diagnosis["awaiting"], "any frame")
        self.assertTrue(ctx.exception.diagnosis["processAlive"])
        with self.assertRaises(HostTimeout) as named:
            host.pump(0.05, awaiting="an expected event")
        self.assertEqual(named.exception.diagnosis["awaiting"], "an expected event")

    def test_exited_runtime_reports_the_exit_code_and_its_stderr(self):
        """A child that exits is reported as EOF with its return code and stderr, not as a timeout."""
        host = self.stub(EXITS)
        with self.assertRaises(EOFError) as ctx:
            host.call("runtime.initialize", dict(probe=True), timeout=5)
        payload = json.loads(str(ctx.exception).split("; ", 1)[1])
        self.assertEqual(payload["reason"], "runtime closed stdout")
        self.assertFalse(payload["processAlive"])
        self.assertEqual(payload["returncode"], 3)
        self.assertIn("stub refused to serve", payload["stderr"])

    def test_progress_restarts_the_idle_budget_instead_of_a_wall_clock_deadline(self):
        """Slow but steady progress does not expire the wait; only silence longer than the budget does."""
        source = ("import sys, time\n"
                  "sys.stdin.readline()\n"
                  "for i in range(4):\n"
                  "    time.sleep(0.12)\n"
                  "    sys.stdout.write('{\"jsonrpc\":\"2.0\",\"method\":\"runtime.event\",\"params\":{}}\\n')\n"
                  "    sys.stdout.flush()\n"
                  "time.sleep(0.12)\n"
                  "sys.stdout.write('{\"jsonrpc\":\"2.0\",\"id\":\"h:1\",\"result\":{\"ok\":true}}\\n')\n"
                  "sys.stdout.flush()\n"
                  "sys.stdin.buffer.read()\n")
        host = self.stub(source)
        # Five gaps of 0.12s each: a 0.4s wall clock would have expired, a 0.4s idle budget does not.
        result = host.call("runtime.initialize", dict(probe=True), timeout=0.4)
        self.assertEqual(result, dict(ok=True))
        self.assertEqual(len(host.events), 4)

    def test_overall_cap_stops_a_runtime_that_chatters_without_answering(self):
        """A Runtime that keeps emitting frames but never answers still fails, with the cap named."""
        source = ("import sys, time\n"
                  "sys.stdin.readline()\n"
                  "while True:\n"
                  "    time.sleep(0.02)\n"
                  "    sys.stdout.write('{\"jsonrpc\":\"2.0\",\"method\":\"runtime.event\",\"params\":{}}\\n')\n"
                  "    sys.stdout.flush()\n")
        host = self.stub(source)
        with self.assertRaises(HostTimeout) as ctx:
            host.call("runtime.initialize", dict(probe=True), timeout=1, overall=0.3)
        diagnosis = ctx.exception.diagnosis
        self.assertEqual(diagnosis["reason"], "runtime never answered this request")
        self.assertEqual(diagnosis["overallBudgetSeconds"], round(budget(0.3), 3))
        self.assertTrue(diagnosis["processAlive"])
        self.assertGreater(diagnosis["framesExchanged"], 1)

    def test_budget_scale_is_configurable_and_falls_back_safely(self):
        """HP_TEST_TIMEOUT_SCALE widens every budget; an absent or unusable value means no scaling."""
        previous = os.environ.get(SCALE_VARIABLE)
        try:
            for value, expected in (("2.5", 2.5), ("0", 1.0), ("-1", 1.0), ("not-a-number", 1.0)):
                os.environ[SCALE_VARIABLE] = value
                self.assertEqual(scale(), expected, value)
                self.assertEqual(budget(4), 4 * expected, value)
            os.environ.pop(SCALE_VARIABLE)
            self.assertEqual(scale(), 1.0)
            self.assertEqual(budget(IDLE_SECONDS), IDLE_SECONDS)
        finally:
            if previous is None:
                os.environ.pop(SCALE_VARIABLE, None)
            else:
                os.environ[SCALE_VARIABLE] = previous


if __name__ == "__main__":
    unittest.main()

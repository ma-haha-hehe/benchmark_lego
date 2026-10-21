"""Evaluation outcomes and adapter errors must remain distinct at the CLI."""
import contextlib
import csv
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_eval


GOAL = run_eval.Brick("blue", "brick_2x2", "blue", [0., 0., 0.], [0., 0., 0.])


class StubEnv(run_eval.BenchmarkEnvAdapter):
    def __init__(self, assembled=False, reset_error=False):
        super().__init__()
        self.assembled = assembled
        self.reset_error = reset_error
        self.closed = False

    def reset_with_instance(self, spec):
        if self.reset_error:
            raise RuntimeError("backend connection failed")
        return None

    def step_env(self, action):
        return None, True, {}

    def get_current_world_state(self):
        return [GOAL] if self.assembled else []

    def close(self):
        self.closed = True


class EvaluationTests(unittest.TestCase):
    def spec(self, name):
        return SimpleNamespace(instance_id=name, final_product=[GOAL],
                               task_class="two_brick_stack", seed=42)

    def evaluate(self, output, names, environments, **extra):
        with patch.object(run_eval, "collect_instance_dirs", return_value=names), \
                patch.object(run_eval, "load_instance", side_effect=self.spec), \
                patch.object(run_eval, "build_env", side_effect=environments), \
                contextlib.redirect_stdout(io.StringIO()):
            return run_eval.run_eval("unused", str(output), "dry_run", None, None,
                                     1, False, extra.get("use_verifier", False), .015, 10)

    def test_completed_failure_is_not_counted_as_success(self):
        environments = [StubEnv(assembled=True), StubEnv()]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "runs" / "metrics.csv"
            summary = self.evaluate(output, ["success", "failure"], environments)
            self.assertEqual(summary, dict(processed=2, successes=1, failures=1,
                                           errors=0, skipped=0))
            with output.open() as stream:
                self.assertEqual([row["success"] for row in csv.DictReader(stream)], ["1", "0"])
        self.assertTrue(all(env.closed for env in environments))

    def test_backend_error_is_separate_and_does_not_stop_later_tasks(self):
        environments = [StubEnv(reset_error=True), StubEnv(assembled=True)]
        with tempfile.TemporaryDirectory() as temporary:
            summary = self.evaluate(Path(temporary) / "metrics.csv", ["error", "success"], environments)
        self.assertEqual(summary, dict(processed=2, successes=1, failures=0, errors=1, skipped=0))
        self.assertTrue(all(env.closed for env in environments))

    def test_verifier_rejection_is_skipped_without_running_environment(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(run_eval, "verify_instance_dir", return_value=(False, ["invalid input"])):
            summary = self.evaluate(Path(temporary) / "metrics.csv", ["invalid"], [], use_verifier=True)
        self.assertEqual(summary, dict(processed=1, successes=0, failures=0, errors=0, skipped=1))

    def test_input_error_is_reported_and_later_tasks_continue(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(run_eval, "collect_instance_dirs", return_value=["bad", "good"]), \
                patch.object(run_eval, "load_instance", side_effect=[ValueError("bad YAML"), self.spec("good")]), \
                patch.object(run_eval, "build_env", return_value=StubEnv(assembled=True)), \
                contextlib.redirect_stdout(io.StringIO()):
            summary = run_eval.run_eval("unused", str(Path(temporary) / "metrics.csv"),
                                       "dry_run", None, None, 1, False, False, .015, 10)
        self.assertEqual((summary["successes"], summary["errors"]), (1, 1))

    def test_cli_returns_nonzero_for_task_failure_or_backend_error(self):
        for environment in [StubEnv(), StubEnv(reset_error=True)]:
            with self.subTest(environment=environment), tempfile.TemporaryDirectory() as temporary, \
                    patch.object(run_eval, "collect_instance_dirs", return_value=["task"]), \
                    patch.object(run_eval, "load_instance", return_value=self.spec("task")), \
                    patch.object(run_eval, "build_env", return_value=environment), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = run_eval.main(["--benchmark_root", "unused", "--method", "dry_run",
                                      "--output_csv", str(Path(temporary) / "metrics.csv")])
                self.assertEqual(code, 1)
            self.assertTrue(environment.closed)

    def test_cli_returns_zero_only_for_successfully_evaluated_tasks(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(run_eval, "collect_instance_dirs", return_value=["task"]), \
                patch.object(run_eval, "load_instance", return_value=self.spec("task")), \
                patch.object(run_eval, "build_env", return_value=StubEnv(assembled=True)), \
                contextlib.redirect_stdout(io.StringIO()):
            code = run_eval.main(["--benchmark_root", "unused", "--method", "dry_run",
                                  "--output_csv", str(Path(temporary) / "metrics.csv")])
        self.assertEqual(code, 0)

    def test_unconfigured_template_and_empty_selection_cannot_succeed(self):
        with patch.object(run_eval, "collect_instance_dirs", return_value=["task"]), \
                patch.object(run_eval, "load_instance", return_value=self.spec("task")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(run_eval.main(["--benchmark_root", "unused", "--method", "dry_run"]), 1)
        self.assertIn("No environment adapter is configured", output.getvalue())
        with patch.object(run_eval, "collect_instance_dirs", return_value=[]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_eval.main(["--benchmark_root", "unused", "--method", "dry_run"]), 1)

    def test_cli_input_error_and_default_local_output(self):
        with patch.object(run_eval, "collect_instance_dirs", side_effect=FileNotFoundError("missing root")), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run_eval.main(["--benchmark_root", "missing", "--method", "dry_run"]), 2)
        args = run_eval.parse_args(["--benchmark_root", "unused", "--method", "dry_run"])
        self.assertEqual(args.output_csv, "runs/eval_results.csv")


if __name__ == "__main__":
    unittest.main()

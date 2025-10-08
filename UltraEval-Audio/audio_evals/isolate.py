import atexit
import os
import shlex
import subprocess
import sys
import logging
from functools import wraps

logger = logging.getLogger(__name__)


def isolated(
    script_path: str, command_args_attr: str = "command_args", pre_command: str = ""
):
    def decorator(cls):
        original_init = cls.__init__

        @wraps(original_init)
        def new_init(self, env_path, requirements_path, *args, **kwargs):
            original_init(self, *args, **kwargs)

            if not env_path:
                raise ValueError("env_path must be provided for isolated models")
            if not requirements_path:
                raise ValueError(
                    "requirements_path must be provided for isolated models"
                )

            env_path = os.path.abspath(os.path.normpath(env_path))
            requirements_path = os.path.abspath(requirements_path)
            script_abspath = os.path.abspath(script_path)

            if not os.path.exists(script_abspath):
                raise FileNotFoundError(
                    f"Isolated script not found: {script_abspath}"
                )

            is_windows = os.name == "nt"
            scripts_dir = "Scripts" if is_windows else "bin"
            python_filename = "python.exe" if is_windows else "python"
            python_executable = os.path.join(env_path, scripts_dir, python_filename)

            if not os.path.exists(python_executable):
                logger.info("Creating virtual environment for isolated model")
                os.makedirs(env_path, exist_ok=True)
                subprocess.run([sys.executable, "-m", "venv", env_path], check=True)

            if not os.path.exists(python_executable):
                raise RuntimeError(
                    f"Failed to locate python interpreter in virtualenv: {python_executable}"
                )

            env_overrides: dict[str, str] = {}

            def run_env_command(command: list[str], *, env_updates: dict[str, str] | None = None):
                env = os.environ.copy()
                merged_updates = env_overrides.copy()
                if env_updates:
                    merged_updates.update(env_updates)
                env.update(merged_updates)
                logger.debug("Running in isolated env: %s", " ".join(command))
                subprocess.run(command, check=True, env=env)

            if pre_command:
                for segment in [c.strip() for c in pre_command.split("&&") if c.strip()]:
                    if segment.startswith("export "):
                        assignment = segment[len("export ") :]
                        key, sep, value = assignment.partition("=")
                        if not sep:
                            logger.warning("Ignoring malformed export command: %s", segment)
                            continue
                        env_overrides[key.strip()] = value.strip()
                        continue

                    args = shlex.split(segment)
                    if not args:
                        continue

                    if args[0] == "pip":
                        run_env_command([python_executable, "-m", *args[0:]])
                    elif args[0] == "python":
                        run_env_command([python_executable, *args[1:]])
                    else:
                        run_env_command(args)

            if os.path.exists(requirements_path):
                run_env_command(
                    [
                        python_executable,
                        "-m",
                        "pip",
                        "install",
                        "-r",
                        requirements_path,
                    ]
                )
            else:
                logger.warning(
                    "Requirements file not found for isolated model: %s",
                    requirements_path,
                )

            python_version = (
                subprocess.check_output(
                    [python_executable, "--version"], text=True
                )
                .strip()
                .split()[1]
            )
            major_minor = ".".join(python_version.split(".")[:2])

            if is_windows:
                lib_path = os.path.join(
                    env_path,
                    "Lib",
                    "site-packages",
                    "nvidia",
                    "nvjitlink",
                    "lib",
                )
            else:
                lib_path = os.path.join(
                    env_path,
                    "lib",
                    f"python{major_minor}",
                    "site-packages",
                    "nvidia",
                    "nvjitlink",
                    "lib",
                )

            command_args = getattr(self, command_args_attr, {})
            cmd = [python_executable, "-u", script_abspath]

            for key, value in command_args.items():
                flag = f"--{key}"
                if value == "":
                    cmd.append(flag)
                else:
                    cmd.extend([flag, str(value)])

            proc_env = os.environ.copy()
            proc_env.update(env_overrides)
            if os.path.exists(lib_path):
                env_key = "PATH" if is_windows else "LD_LIBRARY_PATH"
                current = proc_env.get(env_key, "")
                separator = os.pathsep if current else ""
                proc_env[env_key] = f"{lib_path}{separator}{current}" if current else lib_path

            logger.info("Running command: %s", " ".join(cmd))
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=proc_env,
                bufsize=1,
            )

            try:
                exit_code = self.process.wait(timeout=10)
                stdout, stderr = self.process.communicate()
                logger.info(f"Process exited with code: {exit_code}")
                if stdout:
                    logger.info(f"STDOUT:\n{stdout}")
                if stderr:
                    logger.error(f"STDERR:\n{stderr}")
            except subprocess.TimeoutExpired:
                logger.info("Process is still running after 10 seconds")

            def cleanup():
                if self.process and self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3600)
                    except subprocess.TimeoutExpired:
                        self.process.kill()

            atexit.register(cleanup)

        cls.__init__ = new_init
        return cls

    return decorator

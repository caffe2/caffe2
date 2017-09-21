#!/usr/bin/env python

import os
import shutil
import time
from utils.arg_parse import getParser, getArgs, parse
from utils.git import Git
from utils.custom_logger import getLogger
from utils.subprocess_with_logger import processRun

getParser().add_argument("--config", required=True,
    help="The test config file containing all the tests to run")
getParser().add_argument("--tests_dir", required=True,
    help="The root directory that all tests resides.")
getParser().add_argument("--git_dir", required=True,
    help="The base git directory.")
getParser().add_argument("--git_commit",
    help="The git commit on this benchmark run.")
getParser().add_argument("--host", action="store_true",
    help="Run the benchmark on the host.")
getParser().add_argument("--android", action="store_true",
    help="Run the benchmark on all collected android devices.")
getParser().add_argument("--local_reporter",
    help="Save the result to a directory specified by this argument.")
getParser().add_argument("--interval", type=int,
    help="The minimum time interval in seconds between two benchmark runs.")

class GitDriver(object):
    def __init__(self):
        parse()
        self.git = Git(getArgs().git_dir)
        self.commit_hash = None

    def _setupGit(self):
        if getArgs().git_commit:
            self.git.pull("sf", "benchmarking")
            self.git.checkout(getArgs().git_commit)
            new_commit_hash = self.git.run('rev-parse', 'HEAD')
            if new_commit_hash == self.commit_hash:
                return false
            if getArgs().android:
                shutil.rmtree(getArgs().git_dir + "/build_android")
                build_android = getArgs().git_dir + "/scripts/build_android.sh"
                processRun(build_android)
            if getArgs().host:
                shutil.rmtree(getArgs().git_dir + "/build")
                build_local = getArgs().git_dir + "/scripts/build_local.sh"
                processRun(build_local)
            return true

    def _processConfig(self):
        dir_path = os.path.dirname(os.path.realpath(__file__))
        with open(getArgs().config, 'r') as file:
            content = file.read().splitlines()
            configs = [x.strip().replace('<test_dir>', getArgs().tests_dir) for x in content]
            configs = [(dir_path + "/harness.py " + x +
                " --exec_base_dir " + getArgs().git_dir +
                (" --android" if getArgs().android else "") +
                (" --host" if getArgs().host else "") +
                (" --local_reporter "+ getArgs().local_reporter if getArgs().local_reporter else "") +
                (" --git_commit " + self.commit_hash if self.commit_hash else "")).strip()
                for x in configs]
        return configs

    def runOnce(self, configs):
        if not self._setupGit():
            return
        for config in configs:
            cmds = config.split(' ')
            cmd = [x.strip() for x in cmds]
            getLogger().info("Running: %s", ' '.join(cmd))
            processRun(cmd)

    def run(self):
        configs = self._processConfig()
        interval = getArgs().interval if getArgs().interval else 300
        while True:
            prev_ts = time.time()
            self.runOnce(configs)
            current_ts = time.time()
            if current_ts < prev_ts + interval:
                time.sleep(prev_ts + interval - current_ts)

if __name__ == "__main__":
    app = GitDriver()
    app.run()

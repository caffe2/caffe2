#!/usr/bin/env python3

from platforms.platform_base import PlatformBase
import os.path as path

class AndroidPlatform(PlatformBase):
    def __init__(self, adb):
        super(AndroidPlatform, self).__init__()
        self.adb = adb

    def setupPlatform(self):
        self.adb.push(getArgs().net)
        self.adb.push(getArgs().init_net)
        if getArgs().input_file:
            self.adb.push(getArgs().input_file)
        self.adb.push(getArgs().program)

    def runBenchmark(self):
        basename = path.basename(getArgs().program)
        program = self.adb.dir + basename
        init_net = path.basename(getArgs().init_net)
        net = path.basename(getArgs().net)
        cmd = ["cd", self.adb.dir, "&&", program,
            "--init_net", init_net,
            "--net", net,
            "--input", getArgs().input,
            "--warmup", str(getArgs().warmup),
            "--iter", str(getArgs().iter),
            ]
        if getArgs().input_file:
            input_file = path.basename(getArgs().input_file)
            cmd.extend(["--input_file", input_file])
        if getArgs().input_dims:
            cmd.extend(["--input_dims", getArgs().input_dims])
        if getArgs().output:
            cmd.extend(["--output", getArgs().output])
            self.adb.shell(["rm", "-rf", self.adb.dir + "output"])
            cmd.extend(["--output_folder", self.adb.dir + "output"])
        if getArgs().run_individual:
            cmd.extend(["--run_individual", "true"])
        self.adb.shell(cmd)

    def collectData(self):
        pass

# sideload_client.py
import subprocess
import json
import time

class SideloadClient:
    def __init__(self, namespace="default", pod_name="perf-audit-origin"):
        self.namespace = namespace
        self.pod_name = pod_name

    def _kubectl_exec(self, cmd, timeout=30):
        """Execute command in sideload pod"""
        full_cmd = [
            'kubectl', 'exec', '-n', self.namespace, self.pod_name,
            '--', 'sh', '-c', cmd
        ]
        try:
            result = subprocess.run(full_cmd, capture_output=True,
                                  timeout=timeout, text=True, check=False)
            return result.stdout.strip(), result.returncode
        except:
            return None, -1

    def check_cpu_isolation(self):
        """Verify isolated CPUs"""
        cmd = "cat /sys/devices/system/cpu/isolated"
        out, code = self._kubectl_exec(cmd)
        if code != 0:
            return None
        return out

    def check_tuned_profile(self):
        """Get active tuned profile"""
        cmd = "nsenter -t 1 -m -u -n -i tuned-adm active"
        out, code = self._kubectl_exec(cmd)
        if code != 0:
            return None
        return out.replace('Current active profile:', '').strip()

    def check_irq_affinity(self, irq_pattern=""):
        """Check IRQ affinity for network interfaces"""
        cmd = f"nsenter -t 1 -m -u -n -i bash -c 'grep -H . /proc/irq/*/smp_affinity_list | grep {irq_pattern}'"
        out, code = self._kubectl_exec(cmd, timeout=10)
        if code != 0:
            return None

        # Parse output: /proc/irq/123/smp_affinity_list:0-3
        affinities = {}
        for line in out.split('\n'):
            if ':' in line:
                parts = line.split(':')
                irq_num = parts[0].split('/')[3]
                cpus = parts[1]
                affinities[irq_num] = cpus

        return affinities

    def get_rt_throttling(self):
        """Check RT throttling settings"""
        cmd = "cat /proc/sys/kernel/sched_rt_runtime_us"
        out, code = self._kubectl_exec(cmd)
        if code != 0:
            return None
        return int(out)

    def trigger_perf_record(self, duration=15, frequency=99):
        """Start perf record in background"""
        timestamp = int(time.time())
        perf_file = f"/host-tmp/perf_{timestamp}.data"

        cmd = f"nsenter -t 1 -m -u -n -i perf record -F {frequency} -a -g -o {perf_file} sleep {duration} &"
        out, code = self._kubectl_exec(cmd, timeout=2)

        return {
            'timestamp': timestamp,
            'perf_file': perf_file,
            'duration': duration
        }

    def generate_flamegraph(self, perf_file):
        """Generate flamegraph from perf data"""
        svg_file = perf_file.replace('.data', '.svg')

        cmd = f"nsenter -t 1 -m -u -n -i bash -c 'perf script -i {perf_file} | /opt/FlameGraph/stackcollapse-perf.pl | /opt/FlameGraph/flamegraph.pl > {svg_file}'"
        out, code = self._kubectl_exec(cmd, timeout=60)

        return svg_file if code == 0 else None

    def get_worker_rt_status(self):
        """Complete RT validation"""
        return {
            'isolated_cpus': self.check_cpu_isolation(),
            'tuned_profile': self.check_tuned_profile(),
            'rt_throttling_us': self.get_rt_throttling(),
            'irq_affinity': self.check_irq_affinity()
        }

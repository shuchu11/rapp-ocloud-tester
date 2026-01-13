# sideload_client.py
import subprocess
import json
import time
from pathlib import Path

class SideloadClient:
    def __init__(self, namespace="default", pod_name="perf-audit-origin"):
        self.namespace = namespace
        self.pod_name = pod_name
        self.host_tmp = Path("/host-tmp")

    def _kubectl_exec(self, cmd, timeout=30):
        """Execute command in sideload pod"""
        full_cmd = [
            'kubectl', 'exec', '-n', self.namespace, self.pod_name,
            '--', 'sh', '-c', cmd
        ]
        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                timeout=timeout,
                text=True,
                check=False
            )
            return result.stdout.strip(), result.returncode
        except subprocess.TimeoutExpired:
            return None, -1
        except Exception:
            return None, -1

    def _nsenter_cmd(self, cmd):
        """Wrap command with nsenter to access host namespace"""
        return f"nsenter -t 1 -m -u -n -i {cmd}"

    def check_cpu_isolation(self):
        """Verify isolated CPUs"""
        cmd = "cat /sys/devices/system/cpu/isolated"
        out, code = self._kubectl_exec(cmd)
        if code != 0 or not out:
            return None
        return out

    def check_tuned_profile(self):
        """Get active tuned profile"""
        cmd = self._nsenter_cmd("tuned-adm active")
        out, code = self._kubectl_exec(cmd)
        if code != 0:
            return None
        return out.replace('Current active profile:', '').strip()

    def check_irq_affinity(self, irq_pattern=""):
        """Check IRQ affinity for network interfaces"""
        grep_filter = f"| grep '{irq_pattern}'" if irq_pattern else ""
        cmd = self._nsenter_cmd(
            f"bash -c 'grep -H . /proc/irq/*/smp_affinity_list {grep_filter}'"
        )
        out, code = self._kubectl_exec(cmd, timeout=10)
        if code != 0 or not out:
            return {}

        affinities = {}
        for line in out.split('\n'):
            if ':' not in line:
                continue
            try:
                irq_path, cpus = line.split(':', 1)
                irq_num = irq_path.split('/')[3]
                affinities[irq_num] = cpus.strip()
            except (IndexError, ValueError):
                continue
        return affinities

    def get_rt_throttling(self):
        """Check RT throttling settings"""
        cmd = "cat /proc/sys/kernel/sched_rt_runtime_us"
        out, code = self._kubectl_exec(cmd)
        if code != 0:
            return None
        try:
            return int(out)
        except ValueError:
            return None

    def trigger_perf_record(self, duration=15, frequency=99, cpu_filter=None):
        """Start perf record in background"""
        timestamp = int(time.time())
        perf_file = f"/host-tmp/perf_{timestamp}.data"

        cpu_arg = f"-C {cpu_filter}" if cpu_filter else "-a"
        cmd = self._nsenter_cmd(
            f"perf record -F {frequency} {cpu_arg} -g -o {perf_file} "
            f"sleep {duration} &"
        )

        out, code = self._kubectl_exec(cmd, timeout=2)

        return {
            'timestamp': timestamp,
            'perf_file': perf_file,
            'duration': duration,
            'status': 'triggered' if code == 0 else 'failed'
        }

    def check_perf_completion(self, perf_file):
        """Check if perf record completed"""
        cmd = self._nsenter_cmd(f"test -f {perf_file} && echo 'exists'")
        out, code = self._kubectl_exec(cmd, timeout=5)
        return code == 0 and out == 'exists'

    def generate_flamegraph(self, perf_file):
        """Generate flamegraph from perf data"""
        svg_file = perf_file.replace('.data', '.svg')

        cmd = self._nsenter_cmd(
            f"bash -c 'perf script -i {perf_file} | "
            f"/opt/FlameGraph/stackcollapse-perf.pl | "
            f"/opt/FlameGraph/flamegraph.pl > {svg_file}'"
        )

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

    def get_network_irqs(self, interface_pattern="ens"):
        """Get IRQs for specific network interface"""
        cmd = self._nsenter_cmd(
            f"bash -c 'ls -l /proc/irq/*/$(ls /sys/class/net/{interface_pattern}*/device/msi_irqs 2>/dev/null | head -1) 2>/dev/null'"
        )
        out, code = self._kubectl_exec(cmd, timeout=10)
        if code != 0:
            return []

        irqs = []
        for line in out.split('\n'):
            if '/proc/irq/' in line:
                try:
                    irq_num = line.split('/proc/irq/')[1].split('/')[0]
                    irqs.append(irq_num)
                except IndexError:
                    continue
        return irqs

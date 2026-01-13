from datetime import datetime

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
import os


class InfluxWriter:
    def __init__(self):
        self.url = os.getenv("INFLUXDB_URL","http://192.168.8.69:30138")
        self.token = os.getenv("INFLUX_TOKEN", "")
        self.org = os.getenv("INFLUX_ORG", "")
        self.bucket = os.getenv("INFLUX_BUCKET", "")

        self.client = InfluxDBClient(url=self.url, token=self.token, org=self.org)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)

    def write_test_result(
        self, test_id, execution_id, oru_vendor, results, cpu_breakdown=None
    ):
        """Write test results to InfluxDB"""
        timestamp = datetime.utcnow()

        # Main metrics point
        point = (
            Point("test_execution")
            .tag("test_id", test_id)
            .tag("oru_vendor", oru_vendor)
            .tag("execution_id", str(execution_id))
            .field("successful_runs", results.get("successful_runs", 0))
            .field("avg_throughput_mbps", results.get("avg_throughput_mbps", 0.0))
            .field("avg_jitter_ms", results.get("avg_jitter_ms", 0.0))
            .field("avg_loss_percent", results.get("avg_loss_percent", 0.0))
            .field("avg_rsrp_dbm", results.get("avg_rsrp_dbm", 0.0))
            .field("avg_rsrq_db", results.get("avg_rsrq_db", 0.0))
            .field("avg_sinr_db", results.get("avg_sinr_db", 0.0))
            .field("avg_cpu_percent", results.get("avg_cpu_percent", 0.0))
            .time(timestamp, WritePrecision.NS)
        )

        self.write_api.write(bucket=self.bucket, org=self.org, record=point)

        # CPU breakdown per thread
        if cpu_breakdown:
            for thread_name, cpu_pct in cpu_breakdown.items():
                cpu_point = (
                    Point("thread_cpu")
                    .tag("test_id", test_id)
                    .tag("oru_vendor", oru_vendor)
                    .tag("thread_name", thread_name)
                    .tag("execution_id", str(execution_id))
                    .field("cpu_percent", float(cpu_pct))
                    .time(timestamp, WritePrecision.NS)
                )

                self.write_api.write(bucket=self.bucket, org=self.org, record=cpu_point)

        print(f"[INFLUX] Wrote {test_id} execution {execution_id}")

    def write_teiv_snapshot(self, entities):
        """Write TEIV topology snapshot to InfluxDB"""
        from datetime import datetime

        timestamp = datetime.utcnow()

        for entity in entities:
            entity_type = entity["type"]
            entity_urn = entity["urn"]
            attributes = entity.get("attributes", {})

            if entity_type == "ODUFunction":
                point = (
                    Point("teiv_odu")
                    .tag("entity_urn", entity_urn)
                    .tag("odu_name", attributes.get("gNBDUName", "unknown"))
                )

                # Add fields only if they exist and are valid
                if attributes.get("gNBId"):
                    try:
                        point = point.field("gNBId", int(attributes["gNBId"]))
                    except (ValueError, TypeError):
                        pass

                if attributes.get("mcc"):
                    point = point.field("mcc", str(attributes["mcc"]))

                if attributes.get("mnc"):
                    point = point.field("mnc", str(attributes["mnc"]))

                # FHI 7.2 timing parameters
                for param in [
                    "T1a_cp_dl_min",
                    "T1a_cp_dl_max",
                    "T1a_cp_ul_min",
                    "T1a_cp_ul_max",
                    "T1a_up_min",
                    "T1a_up_max",
                    "Ta4_min",
                    "Ta4_max",
                ]:
                    if attributes.get(param) is not None:
                        try:
                            point = point.field(param, int(attributes[param]))
                        except (ValueError, TypeError):
                            pass

                if attributes.get("absoluteFrequencySSB"):
                    try:
                        point = point.field(
                            "absoluteFrequencySSB",
                            int(attributes["absoluteFrequencySSB"]),
                        )
                    except (ValueError, TypeError):
                        pass

                point = point.time(timestamp, WritePrecision.NS)
                self.write_api.write(bucket=self.bucket, org=self.org, record=point)

            elif entity_type == "NRCellDU":
                point = (
                    Point("teiv_cell")
                    .tag("entity_urn", entity_urn)
                    .tag("cell_name", attributes.get("cellLocalId", "unknown"))
                )

                # Add fields only if they exist
                for param in ["nRPCI", "nRTAC", "arfcnDL", "arfcnUL", "bSChannelBwDL"]:
                    if attributes.get(param) is not None:
                        try:
                            point = point.field(param, int(attributes[param]))
                        except (ValueError, TypeError):
                            pass

                point = point.time(timestamp, WritePrecision.NS)
                self.write_api.write(bucket=self.bucket, org=self.org, record=point)

        print(f"[INFLUX] Wrote TEIV snapshot: {len(entities)} entities")

    def write_teiv_relationship(self, odu_urn, cell_urn):
        """Write ODU → Cell relationship"""
        from datetime import datetime

        point = (
            Point("teiv_relationship")
            .tag("relationship_type", "ODU_PROVIDES_CELL")
            .tag("odu_urn", odu_urn)
            .tag("cell_urn", cell_urn)
            .field("active", 1)
            .time(datetime.utcnow(), WritePrecision.NS)
        )

        self.write_api.write(bucket=self.bucket, org=self.org, record=point)

    def write_thread_cpu_sample(
        self,
        test_id,
        execution_id,
        run_id,
        oru_vendor,
        thread_name,
        cpu_percent,
        core=None,
    ):
        """Write individual thread CPU sample"""
        point = (
            Point("thread_cpu")
            .tag("test_id", test_id)
            .tag("execution_id", str(execution_id))
            .tag("run_id", str(run_id))
            .tag("oru_vendor", oru_vendor)
            .tag("thread_name", thread_name)
        )

        if core:
            point = point.tag("core", str(core))

        point = point.field("cpu_percent", float(cpu_percent))

        self.write_api.write(bucket=self.bucket, org=self.org, record=point)

    def write_test_execution(self, test_id, execution_id, oru_vendor, results):
        """Write main test execution results"""
        timestamp = datetime.utcnow()

        point = (
            Point("test_execution")
            .tag("test_id", test_id)
            .tag("oru_vendor", oru_vendor)
            .tag("execution_id", str(execution_id))
            .field("successful_runs", results.get("successful_runs", 0))
            .field("avg_throughput_mbps", results.get("avg_throughput_mbps", 0.0))
            .field("avg_jitter_ms", results.get("avg_jitter_ms", 0.0))
            .field("avg_loss_percent", results.get("avg_loss_percent", 0.0))
            .field("avg_rsrp_dbm", results.get("avg_rsrp_dbm", 0.0))
            .field("avg_rsrq_db", results.get("avg_rsrq_db", 0.0))
            .field("avg_sinr_db", results.get("avg_sinr_db", 0.0))
            .time(timestamp, WritePrecision.NS)
        )

        self.write_api.write(bucket=self.bucket, org=self.org, record=point)
        print(f"[INFLUX] Wrote test_execution: {test_id}/{execution_id}")

    def write_cpu_monitor(self, test_id, execution_id, run_id, cpu_data):
        """Write CPU core monitoring time-series data"""
        if not cpu_data or "cpus" not in cpu_data:
            return

        for cpu_name, cpu_info in cpu_data["cpus"].items():
            samples = cpu_info.get("samples", [])
            usage = cpu_info.get("usage", [])

            for timestamp, cpu_percent in zip(samples, usage):
                point = (
                    Point("cpu_core_usage")
                    .tag("test_id", test_id)
                    .tag("execution_id", str(execution_id))
                    .tag("run_id", str(run_id))
                    .tag("cpu_name", cpu_name)
                    .field("usage_percent", float(cpu_percent))
                    .time(int(timestamp * 1e9), WritePrecision.NS)
                )

                self.write_api.write(bucket=self.bucket, org=self.org, record=point)

        print(f"[INFLUX] Wrote cpu_core_usage: {test_id}/{execution_id}/run-{run_id}")

    def write_memory_monitor(self, test_id, execution_id, run_id, memory_data):
        """Write memory monitoring time-series data"""
        if not memory_data or "memory" not in memory_data:
            return

        mem = memory_data["memory"]
        samples = mem.get("samples", [])

        for i, timestamp in enumerate(samples):
            point = (
                Point("memory_usage")
                .tag("test_id", test_id)
                .tag("execution_id", str(execution_id))
                .tag("run_id", str(run_id))
                .field("total_kb", mem["total"][i])
                .field("free_kb", mem["free"][i])
                .field("available_kb", mem["available"][i])
                .field("buffers_kb", mem["buffers"][i])
                .field("cached_kb", mem["cached"][i])
                .field("used_kb", mem["used"][i])
                .field("used_percent", float(mem["used_percent"][i]))
                .time(int(timestamp * 1e9), WritePrecision.NS)
            )

            self.write_api.write(bucket=self.bucket, org=self.org, record=point)

        print(f"[INFLUX] Wrote memory_usage: {test_id}/{execution_id}/run-{run_id}")

    def write_disk_monitor(self, test_id, execution_id, run_id, disk_data):
        """Write disk I/O monitoring time-series data"""
        if not disk_data or "disk" not in disk_data:
            return

        disk = disk_data["disk"]
        samples = disk.get("samples", [])
        device = disk_data.get("device", "unknown")

        for i, timestamp in enumerate(samples):
            point = (
                Point("disk_io")
                .tag("test_id", test_id)
                .tag("execution_id", str(execution_id))
                .tag("run_id", str(run_id))
                .tag("device", device)
                .field("read_kb_per_s", float(disk["read_kb"][i]))
                .field("write_kb_per_s", float(disk["write_kb"][i]))
                .field("read_iops", disk["read_iops"][i])
                .field("write_iops", disk["write_iops"][i])
                .time(int(timestamp * 1e9), WritePrecision.NS)
            )

            self.write_api.write(bucket=self.bucket, org=self.org, record=point)

        print(f"[INFLUX] Wrote disk_io: {test_id}/{execution_id}/run-{run_id}")

    def write_hugepages_monitor(self, test_id, execution_id, run_id, hugepage_data):
        """Write hugepages monitoring time-series data"""
        if not hugepage_data or "hugepages" not in hugepage_data:
            return

        hp = hugepage_data["hugepages"]
        samples = hp.get("samples", [])
        pagesize_kb = hugepage_data.get("hugepagesize_kb", 0)

        for i, timestamp in enumerate(samples):
            point = (
                Point("hugepages_usage")
                .tag("test_id", test_id)
                .tag("execution_id", str(execution_id))
                .tag("run_id", str(run_id))
                .field("total", hp["total"][i])
                .field("free", hp["free"][i])
                .field("reserved", hp["reserved"][i])
                .field("surplus", hp["surplus"][i])
                .field("used", hp["used"][i])
                .field("used_percent", float(hp["used_percent"][i]))
                .field("pagesize_kb", pagesize_kb)
                .time(int(timestamp * 1e9), WritePrecision.NS)
            )

            self.write_api.write(bucket=self.bucket, org=self.org, record=point)

        print(f"[INFLUX] Wrote hugepages_usage: {test_id}/{execution_id}/run-{run_id}")

    def close(self):
        self.client.close()

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime

class InfluxWriter:
    def __init__(self):
        self.url = "http://192.168.8.69:30138"
        self.token = "MQ3kTfi8hKjReLdU68Sx7KWtgBZzdiTl1bf6oODfMyovREhBdI85Aewp-iUYYfuVi_IZF3MtBaR8Lat6CqJRcQ=="  # Paste token here
        self.org = "7c10e47173647c1f"
        self.bucket = "test-results"

        self.client = InfluxDBClient(url=self.url, token=self.token, org=self.org)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)

    def write_test_result(self, test_id, execution_id, oru_vendor, results, cpu_breakdown=None):
        """Write test results to InfluxDB"""
        timestamp = datetime.utcnow()

        # Main metrics point
        point = Point("test_execution") \
            .tag("test_id", test_id) \
            .tag("oru_vendor", oru_vendor) \
            .tag("execution_id", str(execution_id)) \
            .field("successful_runs", results.get('successful_runs', 0)) \
            .field("avg_throughput_mbps", results.get('avg_throughput_mbps', 0.0)) \
            .field("avg_jitter_ms", results.get('avg_jitter_ms', 0.0)) \
            .field("avg_loss_percent", results.get('avg_loss_percent', 0.0)) \
            .field("avg_rsrp_dbm", results.get('avg_rsrp_dbm', 0.0)) \
            .field("avg_rsrq_db", results.get('avg_rsrq_db', 0.0)) \
            .field("avg_sinr_db", results.get('avg_sinr_db', 0.0)) \
            .field("avg_cpu_percent", results.get('avg_cpu_percent', 0.0)) \
            .time(timestamp, WritePrecision.NS)

        self.write_api.write(bucket=self.bucket, org=self.org, record=point)

        # CPU breakdown per thread
        if cpu_breakdown:
            for thread_name, cpu_pct in cpu_breakdown.items():
                cpu_point = Point("thread_cpu") \
                    .tag("test_id", test_id) \
                    .tag("oru_vendor", oru_vendor) \
                    .tag("thread_name", thread_name) \
                    .tag("execution_id", str(execution_id)) \
                    .field("cpu_percent", float(cpu_pct)) \
                    .time(timestamp, WritePrecision.NS)

                self.write_api.write(bucket=self.bucket, org=self.org, record=cpu_point)

        print(f"[INFLUX] Wrote {test_id} execution {execution_id}")

    def write_teiv_snapshot(self, entities):
        """Write TEIV topology snapshot to InfluxDB"""
        from datetime import datetime
        timestamp = datetime.utcnow()

        for entity in entities:
            entity_type = entity['type']
            entity_urn = entity['urn']
            attributes = entity.get('attributes', {})

            if entity_type == 'ODUFunction':
                point = Point("teiv_odu") \
                    .tag("entity_urn", entity_urn) \
                    .tag("odu_name", attributes.get('gNBDUName', 'unknown'))

                # Add fields only if they exist and are valid
                if attributes.get('gNBId'):
                    try:
                        point = point.field("gNBId", int(attributes['gNBId']))
                    except (ValueError, TypeError):
                        pass

                if attributes.get('mcc'):
                    point = point.field("mcc", str(attributes['mcc']))

                if attributes.get('mnc'):
                    point = point.field("mnc", str(attributes['mnc']))

                # FHI 7.2 timing parameters
                for param in ['T1a_cp_dl_min', 'T1a_cp_dl_max', 'T1a_cp_ul_min', 'T1a_cp_ul_max',
                             'T1a_up_min', 'T1a_up_max', 'Ta4_min', 'Ta4_max']:
                    if attributes.get(param) is not None:
                        try:
                            point = point.field(param, int(attributes[param]))
                        except (ValueError, TypeError):
                            pass

                if attributes.get('absoluteFrequencySSB'):
                    try:
                        point = point.field("absoluteFrequencySSB", int(attributes['absoluteFrequencySSB']))
                    except (ValueError, TypeError):
                        pass

                point = point.time(timestamp, WritePrecision.NS)
                self.write_api.write(bucket=self.bucket, org=self.org, record=point)

            elif entity_type == 'NRCellDU':
                point = Point("teiv_cell") \
                    .tag("entity_urn", entity_urn) \
                    .tag("cell_name", attributes.get('cellLocalId', 'unknown'))

                # Add fields only if they exist
                for param in ['nRPCI', 'nRTAC', 'arfcnDL', 'arfcnUL', 'bSChannelBwDL']:
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

        point = Point("teiv_relationship") \
            .tag("relationship_type", "ODU_PROVIDES_CELL") \
            .tag("odu_urn", odu_urn) \
            .tag("cell_urn", cell_urn) \
            .field("active", 1) \
            .time(datetime.utcnow(), WritePrecision.NS)

        self.write_api.write(bucket=self.bucket, org=self.org, record=point)

    def close(self):
        self.client.close()

import requests
import json
from datetime import datetime

class TEIVClient:
    def __init__(self, base_url="http://192.168.8.69:30180"):
        self.base = f"{base_url}/topology-inventory/v1alpha11"
        self.cache = {}
        self.relationships = []

    def load_cache(self):
        """Load all O-RUs and Cells from TEIV"""
        print("[TEIV] Loading cache...")

        # Get ODUs
        resp = requests.get(
            f"{self.base}/domains/RAN/entity-types/ODUFunction/entities",
            params={"targetFilter": "/ODUFunction/attributes", "limit": 100}
        )
        for item in resp.json()['items']:
            odu = item['o-ran-smo-teiv-ran:ODUFunction'][0]
            self.cache[odu['id']] = {
                'type': 'ODU',
                'data': odu
            }

        # Get Cells
        resp = requests.get(
            f"{self.base}/domains/RAN/entity-types/NRCellDU/entities",
            params={"targetFilter": "/NRCellDU/attributes", "limit": 100}
        )
        for item in resp.json()['items']:
            cell = item['o-ran-smo-teiv-ran:NRCellDU'][0]
            self.cache[cell['id']] = {
                'type': 'Cell',
                'data': cell
            }

        # Get relationships
        resp = requests.get(
            f"{self.base}/domains/RAN/relationship-types/ODUFUNCTION_PROVIDES_NRCELLDU/relationships",
            params={"limit": 100}
        )
        self.relationships = resp.json()['items']

        print(f"[TEIV] Cached {len(self.cache)} entities, {len(self.relationships)} relationships")
        return len(self.cache)

    def get_odu(self, odu_urn):
        """Get ODU by URN"""
        return self.cache.get(odu_urn, {}).get('data')

    def get_cell(self, cell_urn):
        """Get Cell by URN"""
        return self.cache.get(cell_urn, {}).get('data')

    def get_cell_for_odu(self, odu_urn):
        """Get Cell connected to ODU"""
        for item in self.relationships:
            rel = item['o-ran-smo-teiv-ran:ODUFUNCTION_PROVIDES_NRCELLDU'][0]
            if rel['aSide'] == odu_urn:
                cell_urn = rel['bSide']
                return self.cache.get(cell_urn, {}).get('data')
        return None

    def list_odus(self):
        """List all ODUs"""
        return [
            {'urn': k, 'name': v['data']['attributes'].get('gNBDUName')}
            for k, v in self.cache.items()
            if v['type'] == 'ODU'
        ]

    def get_helm_branch_for_odu(self, odu_urn):
        """Map ODU to Helm branch based on vendor"""
        odu = self.get_odu(odu_urn)
        if not odu:
            return "starlingx/pegatron"  # Default

        name = odu['attributes'].get('gNBDUName', '').lower()

        if 'pegatron' in name:
            return "starlingx/pegatron"
        elif 'liteon' in name:
            return "starlingx/liteon"
        elif 'jura' in name:
            return "starlingx/jura"
        else:
            return "starlingx/pegatron"

    def to_db_format(self):
        """Export cache for SQLite storage"""
        records = []
        for urn, entity in self.cache.items():
            records.append({
                'entity_type': entity['type'],
                'entity_urn': urn,
                'attributes_json': json.dumps(entity['data']['attributes']),
                'cached_at': datetime.now().isoformat()
            })
        return records

if __name__ == "__main__":
    client = TEIVClient()
    client.load_cache()
    print(f"ODUs: {client.list_odus()}")
